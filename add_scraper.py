"""
Alka ADD-feed
=============
Zware feed om NIEUWE producten aan te maken: alle productinfo die alka.nl
publiek toont. Plat per variant, gegroepeerd via `handle` - zo verwacht Stock
Sync het (Variantgroep = handle, Variant Optie 1 = option1).

`published` staat hard op **false**: concept-only. De teksten komen letterlijk
van alka.nl en zijn nog niet langs Themis geweest; publiceren verdien je.
Draai daarom na deze feed `python themis_check.py` en werk het rapport af.
Alka schrijft over "zure afvalstoffen", "ontzuren" en "zuur-base balans" - dat
zijn precies de zinnen waar EFSA/NVWA/KOAG-KAG over gaan.

Wat NIET meekomt uit hun pagina's:
- het blok "Persoonlijk advies" (daar staat het telefoonnummer van Alka's eigen
  adviseurs in) en de FAQ (hun retour- en verzendbeleid, niet het onze);
- de opmaak (achtergrondplaatjes, kolommen); alleen tekstdragende tags blijven.

Bron: alka.nl (publiek). Zie alka_common.py.
Lokaal: INSECURE_SSL=1, MAX_PRODUCTEN=5.
"""

import csv
import os
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom

import alka_common as ac
from scraper import add, korting_pct, nette_naam, pakket_tekst, save_xml

OUTPUT_FILE = "alka_add_feed.xml"
NIEUW_FILE = "alka_add_feed_nieuw.xml"
IN_WINKEL = "alka_in_winkel.txt"
BRON_FILE = "alka_tekstbron.csv"
FEED_URL = ("https://raw.githubusercontent.com/Maximillian-creator/"
            "alka-feed/main/alka_add_feed.xml")


def build_xml(producten):
    root = ET.Element("products")
    for p in producten:
        for v in p["varianten"]:
            afbeeldingen = ac.afbeeldingen_voor(p, v)
            staffel = dict(v["staffel"])
            item = ET.SubElement(root, "product")
            add(item, "handle", p["handle"])
            add(item, "title", p["titel"])
            add(item, "subtitle", p["ondertitel"])
            add(item, "vendor", ac.BRAND)
            add(item, "brand", ac.BRAND)
            add(item, "published", "false")   # concept-only: publiceren verdien je
            add(item, "description", p["omschrijving"])
            add(item, "body_html", p["omschrijving"])
            add(item, "gebruik", p["teksten"].get("instructions", ""))
            add(item, "ingredienten", p["teksten"].get("ingredients", ""))
            add(item, "bron_url", p["url"])
            add(item, "option1_name", "Variant")
            add(item, "option1", v["optie"] or "Standaard")
            add(item, "sku", v["code"])
            add(item, "barcode", v["barcode"])
            add(item, "price", f"{v['adviesprijs']:.2f}")
            add(item, "actieprijs", f"{v['prijs']:.2f}")
            for aantal in (2, 3):
                prijs = staffel.get(aantal)
                add(item, f"staffel{aantal}_prijs", f"{prijs:.2f}" if prijs else "")
                add(item, f"staffel{aantal}_korting_pct",
                    f"{korting_pct(v['prijs'], prijs):.1f}" if prijs else "")
            add(item, "quantity", "0")        # geen eigen voorraad; zie scraper.py
            add(item, "available", "true" if p["op_voorraad"] else "false")
            add(item, "soort", "voordeelpakket" if v["is_pakket"] else "artikel")
            add(item, "pakket_normaal",
                f"{v['pakket_normaal']:.2f}" if v["is_pakket"] else "")
            add(item, "pakket_besparing",
                f"{v['pakket_besparing']:.2f}" if v["is_pakket"] else "")
            add(item, "pakket_inhoud",
                pakket_tekst(v["pakket_inhoud"]) if v["is_pakket"] else "")
            add(item, "variant_title", nette_naam(v["naam"]))
            add(item, "image", afbeeldingen[0] if afbeeldingen else "")
            add(item, "image_links", ",".join(afbeeldingen))
            beelden = ET.SubElement(item, "images")
            for src in afbeeldingen:
                add(ET.SubElement(beelden, "image"), "src", src)
    return root


def schrijf_tekstbron(producten, pad=BRON_FILE):
    """Per variant: waar de tekst vandaan komt en hoeveel het er is.

    Zonder dit bestand is "50 producten met beschrijving" een getal dat je moet
    geloven; hiermee kun je het regel voor regel nakijken.
    """
    with open(pad, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ean", "variantcode", "titel", "optie", "soort", "woorden",
                    "gebruik", "ingredienten", "afbeeldingen", "adviesprijs",
                    "dagprijs", "op_voorraad", "bron_url"])
        for p in producten:
            woorden = len(ac._tekst(p["omschrijving"]).split())
            for v in p["varianten"]:
                w.writerow([
                    v["barcode"], v["code"], p["titel"], v["optie"],
                    "voordeelpakket" if v["is_pakket"] else "artikel", woorden,
                    "ja" if p["teksten"].get("instructions") else "nee",
                    "ja" if p["teksten"].get("ingredients") else "nee",
                    len(p["afbeeldingen"]),
                    f"{v['adviesprijs']:.2f}".replace(".", ","),
                    f"{v['prijs']:.2f}".replace(".", ","),
                    "ja" if p["op_voorraad"] else "nee", p["url"],
                ])
    print(f"Tekstbron geschreven: {pad}")


def reeds_in_winkel():
    """EAN's die al in onze Shopify staan, uit alka_in_winkel.txt (koppeling.py)."""
    if not os.path.exists(IN_WINKEL):
        return None
    return {r.strip() for r in open(IN_WINKEL, encoding="utf-8")
            if r.strip() and not r.startswith("#")}


def schrijf_nieuw_feed(producten):
    """Een tweede feed met alleen de artikelen die wij NIET voeren.

    De volledige add-feed bevat ook wat al in de winkel staat. Wie die op een
    Stock Sync-taak zet die velden bijwerkt, schrijft onze eigen teksten over
    met die van Alka - en die zijn door Themis afgekeurd (24 van de 31 op
    23-09-2026). Deze feed kan dat niet: wat wij al hebben zit er niet in.

    Zonder `alka_in_winkel.txt` wordt er GEEN gefilterde feed geschreven. Een
    ongefilterde feed onder die naam zou het gevaarlijkst zijn wat er is: hij
    heet dan "nieuw" en bevat alles.
    """
    bezet = reeds_in_winkel()
    if bezet is None:
        print(f"{NIEUW_FILE} NIET geschreven: {IN_WINKEL} ontbreekt. "
              f"Draai eerst koppeling.py (die heeft Shopify-toegang nodig).")
        return
    root = build_xml(producten)
    weg = [p for p in root.findall("product") if p.findtext("barcode") in bezet]
    for p in weg:
        root.remove(p)
    save_xml(root, NIEUW_FILE)
    print(f"  {len(weg)} regels eruit (staan al in de winkel), "
          f"{len(root.findall('product'))} nieuw")


def main():
    print("Alka ADD-feed gestart\n")
    start = time.time()
    tel = ac.TelStand()
    producten = ac.fetch_products(tel)
    varianten = ac.controleer(producten, tel)

    save_xml(build_xml(producten), OUTPUT_FILE)
    schrijf_nieuw_feed(producten)
    schrijf_tekstbron(producten)

    dun = [p["handle"] for p in producten
           if len(ac._tekst(p["omschrijving"]).split()) < 30]
    zonder_beeld = [p["handle"] for p in producten if not p["afbeeldingen"]]
    print(f"\nKlaar in {time.time() - start:.0f}s")
    print(f"  {tel.regel()}")
    print(f"  {varianten} regels, {len(dun)} met een dunne beschrijving"
          + (f" ({', '.join(dun)})" if dun else ""))
    print(f"  {len(zonder_beeld)} zonder afbeelding"
          + (f" ({', '.join(zonder_beeld)})" if zonder_beeld else ""))
    print(f"\nFeed-URL voor Stock Sync (Add):\n{FEED_URL}")
    print("\nLet op: draai nu 'python themis_check.py' voordat je iets publiceert.")


if __name__ == "__main__":
    main()
