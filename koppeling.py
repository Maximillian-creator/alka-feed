"""
Koppeling: onze Alka-producten <-> de Alka-feed
===============================================
**Zonder deze stap doet de update-feed niets.** Alle 22 Alka-varianten in onze
Shopify hebben een LEGE SKU én GEEN barcode (peiling 09-09-2026 via de publieke
productlijst). Stock Sync matcht op SKU of barcode; is allebei leeg, dan vindt
hij nul artikelen en werkt hij niets bij - precies de stille fout die eerder een
hele leverancierscatalogus stilzette.

Dit script legt onze producten naast de feed en schrijft een voorstel:

    python koppeling.py            (na scraper.py, die alka_feed.xml maakt)
    -> alka_koppeling.csv

Per regel staat er een oordeel:

  zeker        naam én prijs komen overeen -> barcode overnemen
  controleren  alleen de prijs of alleen de naam komt overeen -> Max kijkt
  onzeker      allebei niet -> waarschijnlijk uit het assortiment van Alka

Het beste voorstel staat er altijd bij, ook bij 'onzeker', met de kolom
`prijsverschil`: wat wij vragen min wat alka.nl vraagt. Drie artikelen staan bij
ons hoger geprijsd dan bij Alka zelf; wie `price` klakkeloos mapt, verlaagt daar
zijn eigen prijs.

Er wordt niets gewijzigd in Shopify. Het CSV is de invoer voor een eenmalige
handmatige import van de barcodes; daarna kan de feed zijn werk doen.
"""

import csv
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

WINKEL = os.environ.get("GFY_WINKEL", "https://goodforyouonline.nl")
FEED = "alka_feed.xml"
UIT = "alka_koppeling.csv"
BARCODES = "alka_barcodes.csv"
UITBREIDING = "alka_uitbreiding.csv"

# Met de hand nagekeken op 10-09-2026, omdat naam of prijs niet vanzelf matcht.
# (onze handle, onze varianttitel) -> (EAN bij Alka, waarom)
# Een lege EAN betekent: bewust GEEN koppeling, met de reden erbij.
HANDKOPPELING = {
    ("alka-basische-scrub-ph-7-6", ""):
        ("8718546785009", "zelfde product, Alka noemt het nu 'Alka® Scrub - 250g'"),
    ("alka-basische-kruiden-thee", "48 zakjes"):
        ("8718546783029", "48 zakjes = 48 filterzakjes; onze prijs ligt €1,50 hoger"),
    ("alka-basische-kruiden-thee", "96 zakjes"):
        ("8718546783050", "96 zakjes = 96 filterzakjes; onze prijs ligt €2,00 hoger"),
    ("alka-greens", "10 Stuks"):
        ("8718546784262", "10 sticks (80g); onze prijs ligt €1,50 hoger"),
    ("alka-greens", "30 Stuks"):
        ("8718546784309", "30 sticks (240g); onze prijs ligt €3,00 hoger"),
    ("alka-badzout", "250 GR"):
        ("8718546782121", "250 gram = de reisverpakking 5 x 50g, zelfde prijs"),
    ("alka®-spermidine-forte", ""):
        ("8718546785320", "zelfde spermidine-chlorellacomplex, Alka liet 'Forte' vallen"),
    ("alka®-scrub-pads", ""):
        ("", "GEEN luffa-scrubsponzen meer in de catalogus van alka.nl (50 varianten "
             "nagelopen op 10-09-2026) - navragen bij de vertegenwoordiger of dit nog "
             "leverbaar is; zo niet: uitfaseren"),
}

# Alleen ons eigen Alka-merk. "Mattisson AlkaGreens" en "Terranova Alkaline"
# heten toevallig ook zo en horen bij een andere leverancier.
ONZE_VENDOR = "alka vitae"


def normaliseer(tekst):
    tekst = (tekst or "").lower().replace("®", " ").replace("®", " ")
    tekst = re.sub(r"\balka\b", " ", tekst)
    tekst = re.sub(r"[^a-z0-9]+", " ", tekst)
    return " ".join(tekst.split())


def winkelproducten():
    producten, pagina = [], 1
    while pagina < 25:
        url = f"{WINKEL}/products.json?limit=250&page={pagina}"
        req = urllib.request.Request(url, headers={"User-Agent": "GFY-AlkaFeed/1.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            blok = json.load(r).get("products", [])
        if not blok:
            break
        producten += blok
        pagina += 1
    return [p for p in producten if (p.get("vendor") or "").lower() == ONZE_VENDOR]


def feedvarianten(pad=FEED):
    root = ET.parse(pad).getroot()
    return [{
        "barcode": p.findtext("barcode") or "",
        "sku": p.findtext("sku") or "",
        "titel": p.findtext("title") or "",
        "prijs": float(p.findtext("actieprijs") or 0),
        "soort": p.findtext("soort") or "",
        "url": p.findtext("bron_url") or "",
    } for p in root.findall("product")]


def gelijkenis(a, b):
    """Letters én woorden. Alleen letters vergelijken zet '48 zakjes' naast
    '96 filterzakjes'; de getallen in een supplementnaam zijn juist beslissend."""
    ta, tb = set(a.split()), set(b.split())
    overlap = len(ta & tb) / len(ta | tb) if ta | tb else 0
    return max(SequenceMatcher(None, a, b).ratio(), overlap)


def beste(onze_titel, onze_prijs, kandidaten):
    genormaliseerd = normaliseer(onze_titel)
    gescoord = []
    for k in kandidaten:
        naam = gelijkenis(genormaliseerd, normaliseer(k["titel"]))
        prijs_gelijk = abs(k["prijs"] - onze_prijs) < 0.005
        gescoord.append((naam + (0.3 if prijs_gelijk else 0), naam, prijs_gelijk, k))
    gescoord.sort(key=lambda r: -r[0])
    return gescoord[0] if gescoord else None


def main():
    if not os.path.exists(FEED):
        print(f"{FEED} ontbreekt - draai eerst 'python scraper.py'")
        return 1
    kandidaten = feedvarianten()
    onze = winkelproducten()
    print(f"{len(onze)} producten met merk '{ONZE_VENDOR}' in de winkel, "
          f"{len(kandidaten)} varianten in de feed\n")

    per_ean = {k["barcode"]: k for k in kandidaten}
    tellen = {"handmatig": 0, "zeker": 0, "controleren": 0, "onzeker": 0,
              "niet leverbaar": 0}
    gekoppeld, tezetten = set(), []

    with open(UIT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["onze handle", "ons product", "onze prijs", "onze sku",
                    "onze barcode", "oordeel", "barcode (ean)",
                    "variantcode", "artikel bij alka", "prijs bij alka",
                    "prijsverschil", "naamgelijkenis", "toelichting", "bron"])
        for p in onze:
            for v in p["variants"]:
                prijs = float(v.get("price") or 0)
                varianttitel = "" if v.get("title") in (None, "Default Title") \
                    else v["title"]
                titel = p["title"] if not varianttitel \
                    else f"{p['title']} {varianttitel}"
                _, naamscore, prijs_gelijk, k = beste(titel, prijs, kandidaten)

                hand = HANDKOPPELING.get((p["handle"], varianttitel))
                if hand:
                    ean, toelichting = hand
                    k = per_ean.get(ean, k) if ean else None
                    oordeel = "handmatig" if ean else "niet leverbaar"
                    naamscore = 1.0 if ean else 0.0
                elif naamscore >= 0.6 and prijs_gelijk:
                    oordeel, toelichting = "zeker", ""
                elif naamscore >= 0.4 or prijs_gelijk:
                    oordeel, toelichting = "controleren", ""
                else:
                    oordeel, toelichting = "onzeker", ""
                tellen[oordeel] += 1

                verschil = (prijs - k["prijs"]) if k else 0.0
                if oordeel in ("handmatig", "zeker") and k:
                    gekoppeld.add(k["barcode"])
                    tezetten.append((p, v, varianttitel, titel, prijs, k, verschil))
                w.writerow([
                    p["handle"], titel, f"{prijs:.2f}".replace(".", ","),
                    v.get("sku") or "", v.get("barcode") or "", oordeel,
                    k["barcode"] if k else "", k["sku"] if k else "",
                    k["titel"] if k else "",
                    f"{k['prijs']:.2f}".replace(".", ",") if k else "",
                    f"{verschil:+.2f}".replace(".", ",") if k else "",
                    f"{naamscore:.2f}".replace(".", ","), toelichting,
                    k["url"] if k else "",
                ])
                merk = {"handmatig": "* ", "zeker": "  ", "controleren": "? ",
                        "onzeker": "! ", "niet leverbaar": "X "}[oordeel]
                print(f"{merk}{titel[:42]:42} EUR {prijs:>6.2f}  ->  {oordeel:15} "
                      f"{(k['titel'][:36] if k else '-'):36} "
                      + (f"({verschil:+.2f})" if k else ""))

    # 1. De regels die klaarstaan om in Shopify gezet te worden.
    with open(BARCODES, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["handle", "product", "variant", "variant id", "barcode zetten",
                    "sku zetten", "onze prijs", "prijs bij alka", "prijsverschil",
                    "let op"])
        for p, v, varianttitel, titel, prijs, k, verschil in tezetten:
            w.writerow([
                p["handle"], p["title"], varianttitel or "Default Title", v["id"],
                k["barcode"], k["sku"], f"{prijs:.2f}".replace(".", ","),
                f"{k['prijs']:.2f}".replace(".", ","),
                f"{verschil:+.2f}".replace(".", ","),
                "onze prijs wijkt af van alka.nl" if abs(verschil) >= 0.005 else "",
            ])
    print(f"\nGeschreven: {BARCODES} ({len(tezetten)} varianten klaar om te zetten)")

    # 2. Wat Alka voert en wij niet - de uitbreidingskant.
    ontbreekt = [k for k in kandidaten if k["barcode"] not in gekoppeld]
    with open(UITBREIDING, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["barcode (ean)", "variantcode", "artikel", "soort",
                    "prijs bij alka", "bron"])
        for k in sorted(ontbreekt, key=lambda x: (x["soort"], x["titel"])):
            w.writerow([k["barcode"], k["sku"], k["titel"], k["soort"],
                        f"{k['prijs']:.2f}".replace(".", ","), k["url"]])
    pakketten = sum(1 for k in ontbreekt if k["soort"] == "voordeelpakket")
    print(f"Geschreven: {UITBREIDING} ({len(ontbreekt)} varianten die wij niet "
          f"voeren, waarvan {pakketten} voordeelpakketten)")

    print(f"\nGeschreven: {UIT}")
    print("  " + " | ".join(f"{k} {v}" for k, v in tellen.items() if v))
    print("\nZolang de barcode in Shopify leeg blijft, doet de update-feed voor "
          "dat artikel niets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
