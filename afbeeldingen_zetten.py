"""
Afbeeldingen per variant koppelen
=================================
Stock Sync zet de foto's wél in het product, maar koppelt ze niet aan de
variant. Gevolg: alle vier de Badzout-varianten (600g, 1.200g, 2.400g,
reisverpakking) tonen hetzelfde plaatje, terwijl Alka voor elk een eigen foto
heeft. Dit script legt die koppeling.

    python afbeeldingen_zetten.py            # DROOGLOOP
    python afbeeldingen_zetten.py --doen     # schrijft echt

Wat het doet, per variant met een EAN uit `alka_feed.xml`:

  1. de eigen foto van die variant opzoeken (`image` in de feed - Alka hangt
     zijn beelden aan variantcodes, zie alka_common.afbeeldingen_voor);
  2. staat die foto nog niet bij het product, dan uploaden;
  3. de variant eraan koppelen.

Wat het NIET doet: bestaande media weggooien. Eigen fotografie blijft staan;
alleen de koppeling per variant wordt gezet. Wil je de oude beelden eruit, dan
is dat een aparte, bewuste opruiming.

Varianten die al de juiste foto hebben worden overgeslagen.
"""

import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

from barcodes_zetten import toegang, graphql

HIER = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HIER, "alka_feed.xml")
VENDOR = "Alka Vitae"

PRODUCTEN = """
query($cursor: String) {
  products(first: 100, after: $cursor, query: "vendor:'%s'") {
    pageInfo { hasNextPage endCursor }
    edges { node { id handle title status
      media(first: 50) { edges { node { ... on MediaImage { id status image { url } } } } }
      variants(first: 50) { edges { node { id title barcode image { url } } } } } } } }
""" % VENDOR

UPLOAD = """
mutation($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media { ... on MediaImage { id status } }
    mediaUserErrors { field message } } }
"""

KOPPEL = """
mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { title image { url } }
    userErrors { field message } } }
"""

MEDIA = """
query($id: ID!) {
  product(id: $id) { media(first: 50) { edges { node {
    ... on MediaImage { id status image { url } } } } } } }
"""


def bestandsnaam(url):
    """De naam waarop we een bronfoto en een geuploade foto herkennen.

    Twee dingen veranderen onderweg, en allebei braken de vergelijking:
    - Alka's pad bevat spaties (`...stap%201-2.jpg`); Shopify bewaart die als
      `_20` (`...stap_201-2.jpg`). Wie op de underscore afknipt, houdt
      "...-stap" over en denkt dat de foto er nog niet is - dat leverde op
      23-09-2026 vijf dubbele uploads op;
    - bij een naambotsing plakt Shopify er een hash achter
      (`...-voorkant_4d49911.jpg`).
    Deze vergelijking is alleen voor "staat die foto er al?". Het koppelen
    zelf gaat op de media-id die de upload teruggeeft, want dat kan niet
    misgaan.
    """
    naam = urllib.parse.unquote((url or "").split("?")[0].rsplit("/", 1)[-1])
    naam = naam.rsplit(".", 1)[0]
    # Botsings-suffix van Shopify: soms een korte hash (`_4d49911`), soms een
    # hele UUID (`_7aa2097c-9d0b-4...`). Allebei eraf.
    naam = re.sub(r"_[0-9a-f]{6,}(?:-[0-9a-f]{4,})*$", "", naam)
    naam = naam.replace("_20", "-")                 # Shopify's vorm van %20
    return re.sub(r"[^a-z0-9]+", "-", naam.lower()).strip("-")


def feed_fotos():
    """barcode -> (hoofdfoto, alle foto's) volgens de feed."""
    uit = {}
    for p in ET.parse(FEED).getroot().findall("product"):
        ean = p.findtext("barcode")
        hoofd = p.findtext("image") or ""
        alle = [u for u in (p.findtext("image_links") or "").split(",") if u]
        if ean and hoofd:
            uit[ean] = (hoofd, alle)
    return uit


def winkel(store, token):
    rijen, cursor = [], None
    while True:
        d = graphql(store, token, PRODUCTEN, {"cursor": cursor})["products"]
        rijen += [e["node"] for e in d["edges"]]
        if not d["pageInfo"]["hasNextPage"]:
            return rijen
        cursor = d["pageInfo"]["endCursor"]


def wacht_tot_klaar(store, token, product_id, ids, pogingen=15):
    """Uploads zijn asynchroon; koppelen kan pas als de media READY is."""
    ids = set(ids)
    for _ in range(pogingen):
        time.sleep(3)
        med = [e["node"] for e in
               graphql(store, token, MEDIA, {"id": product_id})["product"]["media"]["edges"]]
        klaar = {m["id"] for m in med if m.get("status") == "READY"}
        if ids <= klaar:
            return ids
    return ids & klaar


def main():
    doen = "--doen" in sys.argv
    store, token = toegang()
    if not (store and token):
        print("Geen toegang tot Shopify - zie barcodes_zetten.py")
        return 1
    fotos = feed_fotos()
    producten = winkel(store, token)
    print(f"{len(producten)} producten van {VENDOR}, {len(fotos)} artikelen met "
          f"foto's in de feed"
          + ("" if doen else "   (DROOGLOOP - er wordt niets geschreven)") + "\n")

    gezet = overgeslagen = 0
    for p in producten:
        aanwezig = {bestandsnaam((e["node"].get("image") or {}).get("url")): e["node"]["id"]
                    for e in p["media"]["edges"]}
        werk = []           # (variant, gewenste url, stam)
        for e in p["variants"]["edges"]:
            v = e["node"]
            bron = fotos.get(v.get("barcode"), (None, None))[0]
            if not bron:
                continue
            stam = bestandsnaam(bron)
            if bestandsnaam((v.get("image") or {}).get("url")) == stam:
                overgeslagen += 1
                continue
            werk.append((v, bron, stam))
        if not werk:
            continue

        print(f"  {p['title'][:34]:34} {p['status'][:5]:5} {len(werk)} variant(en)")
        for v, bron, stam in werk:
            staat_er = "al bij het product" if stam in aanwezig else "moet geupload"
            print(f"      {v['title'][:26]:26} <- {bron.rsplit('/', 1)[-1][:46]} ({staat_er})")
        if not doen:
            gezet += len(werk)
            continue

        # 1. ontbrekende foto's uploaden; het antwoord geeft de media-ids
        #    terug in dezelfde volgorde als de invoer.
        nieuw = [(bron, stam) for _, bron, stam in werk if stam not in aanwezig]
        if nieuw:
            d = graphql(store, token, UPLOAD, {
                "productId": p["id"],
                "media": [{"originalSource": bron, "mediaContentType": "IMAGE",
                           "alt": p["title"]} for bron, _ in nieuw]})["productCreateMedia"]
            if d.get("mediaUserErrors"):
                print(f"      ! upload-fout: {d['mediaUserErrors']}")
                continue
            verse = {stam: m["id"] for (_, stam), m in zip(nieuw, d["media"])}
            klaar = wacht_tot_klaar(store, token, p["id"], verse.values())
            aanwezig.update({s: i for s, i in verse.items() if i in klaar})

        # 2. koppelen
        updates = [{"id": v["id"], "mediaId": aanwezig[stam]}
                   for v, _, stam in werk if stam in aanwezig]
        ontbreekt = [v["title"] for v, _, stam in werk if stam not in aanwezig]
        if ontbreekt:
            print(f"      ! media niet op tijd klaar voor: {', '.join(ontbreekt)}")
        if updates:
            r = graphql(store, token, KOPPEL,
                        {"productId": p["id"], "variants": updates})["productVariantsBulkUpdate"]
            if r.get("userErrors"):
                print(f"      ! koppel-fout: {r['userErrors']}")
            else:
                gezet += len(updates)
                for pv in r["productVariants"]:
                    f = (pv.get("image") or {}).get("url", "")
                    print(f"      ok {pv['title'][:26]:26} {f.rsplit('/', 1)[-1][:44]}")

    print(f"\n{gezet} variant(en) {'gekoppeld' if doen else 'te koppelen'}, "
          f"{overgeslagen} stond al goed.")
    if not doen:
        print("Draai opnieuw met --doen om het echt te schrijven.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
