"""
Barcodes zetten in Shopify
==========================
Zet de EAN (en de variantcode van Alka als SKU) op onze Alka-varianten, zodat
Stock Sync de feed kan matchen. Leest `alka_barcodes.csv`, dat `koppeling.py`
schrijft.

    python barcodes_zetten.py                 # DROOGLOOP: toont alleen wat er zou gebeuren
    python barcodes_zetten.py --doen          # schrijft echt
    python barcodes_zetten.py --overschrijf   # ook varianten die al een ANDERE barcode hebben

Sloten:
- Een variant die al een barcode heeft die afwijkt van het voorstel wordt
  OVERGESLAGEN, niet overschreven. Dat is de enige onomkeerbare fout die hier
  gemaakt kan worden. Met `--overschrijf` gebeurt het wel; de oude waarde staat
  dan in het logboek, zodat het terug te draaien is. Gebruikt op 23-09-2026 voor
  de vier varianten die nog de EAN van de vorige productversie droegen (Thee
  48/96, Greens 10/30), op verzoek van Max.
- Hetzelfde voor een SKU die al gevuld is.
- Elke wijziging komt in `alka_barcodes_gezet.csv` te staan: wat er stond, wat
  er nu staat, en het antwoord van Shopify. Zonder dat logboek is "21 gezet"
  een getal dat je moet geloven.

Toegang: net als de andere agents haalt dit script zélf een token op met de
CLIENT_ID + CLIENT_SECRET van de custom app (client_credentials-grant, zie
`gfy-orderdata`: `shopify_token_client_credentials`). Er hoeft dus **geen**
`shpat_`-token ergens te staan, en er mag zeker geen nieuw token gemaakt of
geroteerd worden - dat zou de agents op de VPS stilzetten.

Gezocht wordt, in deze volgorde:

  1. de omgevingsvariabelen SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET
  2. `.env` naast dit script
  3. `../../gfy-gaia/.env` (waar ze in dit project al stonden)

Een los SHOPIFY_ADMIN_TOKEN wordt gebruikt als het er is. Nodig: scope
`write_products` (stond op 23-09-2026 aan).

Schrijf een `.env` NIET met PowerShell Set-Content of Out-File -Encoding utf8 -
die zetten een BOM voor de eerste regel en dan is de eerste variabele stuk.
"""

import csv
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
INVOER = os.path.join(HIER, "alka_barcodes.csv")
LOGBOEK = os.path.join(HIER, "alka_barcodes_gezet.csv")
API = "2024-10"

MUTATIE = """
mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id barcode sku }
    userErrors { field message }
  }
}
"""

VRAAG = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on ProductVariant { id title barcode sku product { id title } }
  }
}
"""


def _lees_env(pad):
    waarden = {}
    if os.path.exists(pad):
        for regel in open(pad, encoding="utf-8-sig"):
            regel = regel.strip()
            if regel and not regel.startswith("#") and "=" in regel:
                k, v = regel.split("=", 1)
                waarden[k.strip()] = v.strip().strip('"')
    return waarden


def _ssl_context():
    ctx = ssl.create_default_context()
    if os.environ.get("INSECURE_SSL") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def toegang():
    """Store + token. Het token wordt zo nodig vers opgehaald met de client-app."""
    waarden = {}
    for pad in (os.path.join(HIER, ".env"),
                os.path.join(HIER, "..", "..", "gfy-gaia", ".env")):
        for k, v in _lees_env(pad).items():
            waarden.setdefault(k, v)

    def haal(naam):
        return (os.environ.get(naam) or waarden.get(naam) or "").strip()

    store = haal("SHOPIFY_STORE")
    token = haal("SHOPIFY_ADMIN_TOKEN")
    if store and token:
        return store, token

    cid, secret = haal("SHOPIFY_CLIENT_ID"), haal("SHOPIFY_CLIENT_SECRET")
    if not (store and cid and secret):
        return store, None
    data = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret,
        "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        f"https://{store}/admin/oauth/access_token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
        return store, json.loads(r.read())["access_token"]


def graphql(store, token, query, variabelen):
    req = urllib.request.Request(
        f"https://{store}/admin/api/{API}/graphql.json",
        data=json.dumps({"query": query, "variables": variabelen}).encode(),
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"})
    antwoord = json.load(urllib.request.urlopen(req, timeout=40,
                                                context=_ssl_context()))
    if antwoord.get("errors"):
        raise SystemExit(f"Shopify gaf een fout: {antwoord['errors']}")
    return antwoord["data"]


def lees_voorstel():
    with open(INVOER, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f, delimiter=";") if r.get("barcode zetten")]


def main():
    doen = "--doen" in sys.argv
    overschrijf = "--overschrijf" in sys.argv
    store, token = toegang()
    if not (store and token):
        print("Geen toegang tot Shopify: SHOPIFY_STORE plus ofwel een "
              "ADMIN_TOKEN ofwel CLIENT_ID + CLIENT_SECRET ontbreken.")
        print("Zie de uitleg bovenin dit script. Maak GEEN nieuw token aan.")
        return 1
    if not os.path.exists(INVOER):
        print(f"{os.path.basename(INVOER)} ontbreekt - draai eerst 'python koppeling.py'")
        return 1

    voorstel = lees_voorstel()
    print(f"{len(voorstel)} varianten in het voorstel"
          + ("" if doen else "  (DROOGLOOP - er wordt niets geschreven)") + "\n")

    # Eerst ophalen wat er NU staat. Nooit schrijven op basis van een bestand
    # dat een week oud kan zijn.
    ids = [f"gid://shopify/ProductVariant/{r['variant id']}" for r in voorstel]
    huidig = {}
    for i in range(0, len(ids), 50):
        for n in graphql(store, token, VRAAG, {"ids": ids[i:i + 50]})["nodes"]:
            if n:
                huidig[n["id"].rsplit("/", 1)[-1]] = n

    doen_lijst, overslaan = [], []
    for r in voorstel:
        vid = r["variant id"]
        nu = huidig.get(vid)
        if nu is None:
            overslaan.append((r, "variant bestaat niet meer in de winkel"))
            continue
        if nu.get("barcode") and nu["barcode"] != r["barcode zetten"]:
            if not overschrijf:
                overslaan.append((r, f"heeft al barcode {nu['barcode']}"))
                continue
            print(f"  VERVANGEN  {r['product'][:38]:38} {r['variant'][:18]:18} "
                  f"{nu['barcode']} -> {r['barcode zetten']}")
        if nu.get("barcode") == r["barcode zetten"] and (nu.get("sku") or "") == r["sku zetten"]:
            overslaan.append((r, "stond al goed"))
            continue
        doen_lijst.append((r, nu))

    for r, reden in overslaan:
        print(f"  overslaan  {r['product'][:38]:38} {r['variant'][:18]:18} {reden}")
    for r, nu in doen_lijst:
        print(f"  zetten     {r['product'][:38]:38} {r['variant'][:18]:18} "
              f"barcode {r['barcode zetten']}  sku {r['sku zetten']}")

    if not doen:
        print(f"\n{len(doen_lijst)} te zetten, {len(overslaan)} overgeslagen.")
        print("Draai opnieuw met --doen om het echt te schrijven.")
        return 0
    if not doen_lijst:
        print("\nNiets te doen.")
        return 0

    # Per product bundelen: de mutatie werkt per product.
    per_product = {}
    for r, nu in doen_lijst:
        per_product.setdefault(r["product id"], []).append((r, nu))

    gelukt, mislukt = 0, 0
    with open(LOGBOEK, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["product", "variant", "variant id", "barcode was",
                    "barcode nu", "sku was", "sku nu", "resultaat"])
        for product_id, regels in per_product.items():
            varianten = [{
                "id": f"gid://shopify/ProductVariant/{r['variant id']}",
                "barcode": r["barcode zetten"],
                "inventoryItem": {"sku": r["sku zetten"]},
            } for r, _ in regels]
            data = graphql(store, token, MUTATIE, {
                "productId": f"gid://shopify/Product/{product_id}",
                "variants": varianten,
            })["productVariantsBulkUpdate"]
            fouten = "; ".join(f"{u['field']}: {u['message']}"
                               for u in data.get("userErrors", []))
            terug = {v["id"].rsplit("/", 1)[-1]: v
                     for v in (data.get("productVariants") or [])}
            for r, nu in regels:
                v = terug.get(r["variant id"])
                ok = v and v.get("barcode") == r["barcode zetten"]
                gelukt, mislukt = (gelukt + 1, mislukt) if ok else (gelukt, mislukt + 1)
                w.writerow([r["product"], r["variant"], r["variant id"],
                            nu.get("barcode") or "", (v or {}).get("barcode") or "",
                            nu.get("sku") or "", (v or {}).get("sku") or "",
                            "ok" if ok else (fouten or "geen bevestiging")])
                print(f"  {'ok  ' if ok else 'FOUT'}       {r['product'][:38]:38} "
                      f"{r['variant'][:18]:18} {(v or {}).get('barcode') or fouten}")

    print(f"\n{gelukt} gezet, {mislukt} mislukt, {len(overslaan)} overgeslagen.")
    print(f"Logboek: {os.path.basename(LOGBOEK)}")
    return 1 if mislukt else 0


if __name__ == "__main__":
    sys.exit(main())
