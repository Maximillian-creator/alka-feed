"""
Alka UPDATE-feed
================
Lichte feed om BESTAANDE producten bij te werken: prijs + beschikbaarheid.

  price        = adviesprijs van Alka (de doorgestreepte prijs, incl. BTW)
  actieprijs   = wat alka.nl vandaag vraagt voor 1 stuk
  staffel2/3   = prijs per stuk bij 2 en 3 stuks (de bundelkorting van alka.nl)
  laagste_*    = de goedkoopste stuksprijs en vanaf hoeveel stuks die geldt
  pakket_*     = bij een voordeelpakket: normale prijs, besparing en inhoud
  quantity     = 0, altijd. Wij houden geen Alka-magazijnstand aan; een getal
                 uit hun webshop zou hier niets betekenen.
  available    = kan Alka vandaag leveren, ja/nee. Map dit in Stock Sync op het
                 VOORRAADBELEID, niet op een aantal.
  sku          = de variantcode van Alka (AV150.1.3.NL)
  barcode      = EAN
  description  = de volledige tekst van alka.nl (info + gebruik + ingredienten).
                 EENMALIG mappen; zie hieronder.
  image /      = de foto's van DEZE variant. Alka koppelt zijn afbeeldingen aan
  image_links    variantcodes, dus elke Deo-geur krijgt zijn eigen flesje. Heeft
                 een variant geen eigen foto's, dan die van de productpagina.

**De staffel is de consumentenkorting van alka.nl zelf, geen inkoopafspraak.**
Er staat bewust geen kostprijs in de feed: wat wij bij Alka betalen ligt niet
vast in dit project. Zie README.md.

**`description` zit er WEL in, maar map hem alleen EENMALIG.** Deze feed draait
2x per dag. Laat je `description` in de Stock Sync-mapping staan, dan zet hij
elke twaalf uur de tekst terug naar die van Alka - ook over een herschrijving
van Nova heen. Map hem dus voor die ene run en haal hem er daarna uit. (Bij
Vitakruid ging het precies zo mis met de titels.)

De tekst is onbewerkt van alka.nl: Themis keurde er op 23-09-2026 24 van de 31
af. Op een concept is dat geen probleem, op een LIVE pagina wel. Zet er dus
kort daarna de burst-run overheen (gfy-nova/batch.py).

Naast de XML schrijft dit script `alka_staffelkortingen.csv` - dezelfde
bundelkortingen, maar leesbaar, om naast de inkoopprijzen te leggen.

Bron: alka.nl (publiek). Zie alka_common.py.
Lokaal: INSECURE_SSL=1, MAX_PRODUCTEN=5.
"""

import csv
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom

import alka_common as ac

OUTPUT_FILE = "alka_feed.xml"
STAFFEL_FILE = "alka_staffelkortingen.csv"
FEED_URL = ("https://raw.githubusercontent.com/Maximillian-creator/"
            "alka-feed/main/alka_feed.xml")


def add(parent, tag, waarde):
    el = ET.SubElement(parent, tag)
    el.text = "" if waarde is None else str(waarde)
    return el


def nette_naam(naam):
    """'Alka® Bitter - 50ml - Original - biologisch - NL' -> zonder landcode."""
    for staart in (" - NL", " - Multi-Lang", " - Multi"):
        if naam.endswith(staart):
            naam = naam[: -len(staart)]
    return naam.strip()


def korting_pct(basis, prijs):
    """Hoeveel procent goedkoper per stuk. Berekend, niet overgenomen: alka.nl
    rondt zijn eigen badge naar beneden af (25,49 van 26,95 = 5,4%, zij tonen
    -5%). Zie test_feed.py, die deze twee tegen elkaar legt."""
    if not basis:
        return 0.0
    return round((basis - prijs) / basis * 100, 1)


def pakket_tekst(inhoud):
    return "; ".join(f"{n}x {nette_naam(naam)} (€ {prijs:.2f})"
                     for n, naam, prijs in inhoud)


def build_xml(producten):
    root = ET.Element("products")
    for p in producten:
        for v in p["varianten"]:
            staffel = dict(v["staffel"])
            laagste = min([v["prijs"]] + list(staffel.values()))
            vanaf = min([a for a, pr in staffel.items() if pr == laagste] or [1])

            item = ET.SubElement(root, "product")
            add(item, "sku", v["code"])
            add(item, "barcode", v["barcode"])
            add(item, "title", nette_naam(v["naam"]))
            add(item, "vendor", ac.BRAND)
            add(item, "price", f"{v['adviesprijs']:.2f}")
            add(item, "actieprijs", f"{v['prijs']:.2f}")
            add(item, "quantity", "0")
            add(item, "available", "true" if p["op_voorraad"] else "false")
            add(item, "handle", p["handle"])
            add(item, "option1", v["optie"] or "Standaard")
            add(item, "soort", "voordeelpakket" if v["is_pakket"] else "artikel")

            # De bundelkorting van alka.nl: prijs per stuk bij 2 en 3 stuks.
            for aantal in (2, 3):
                prijs = staffel.get(aantal)
                add(item, f"staffel{aantal}_prijs",
                    f"{prijs:.2f}" if prijs else "")
                add(item, f"staffel{aantal}_korting_pct",
                    f"{korting_pct(v['prijs'], prijs):.1f}" if prijs else "")
            add(item, "laagste_stuksprijs", f"{laagste:.2f}")
            add(item, "laagste_stuksprijs_vanaf", vanaf)

            add(item, "pakket_normaal",
                f"{v['pakket_normaal']:.2f}" if v["is_pakket"] else "")
            add(item, "pakket_besparing",
                f"{v['pakket_besparing']:.2f}" if v["is_pakket"] else "")
            add(item, "pakket_inhoud",
                pakket_tekst(v["pakket_inhoud"]) if v["is_pakket"] else "")
            add(item, "bron_url", p["url"])

            # Alleen voor een eenmalige tekst-inhaalslag; zie de kop van dit
            # bestand. Niet permanent mappen.
            add(item, "description", p["omschrijving"])

            # Afbeeldingen per EAN: Alka hangt zijn foto's aan variantcodes,
            # dus de Deo-varianten krijgen elk hun eigen flesje mee.
            beelden = ac.afbeeldingen_voor(p, v)
            add(item, "image", beelden[0] if beelden else "")
            add(item, "image_links", ",".join(beelden))
            blok = ET.SubElement(item, "images")
            for src in beelden:
                add(ET.SubElement(blok, "image"), "src", src)
    return root


def schrijf_staffel_csv(producten, pad=STAFFEL_FILE):
    """De bundelkortingen op één rij per artikel, om naast de inkoop te leggen."""
    with open(pad, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ean", "variantcode", "artikel", "soort", "adviesprijs",
                    "prijs 1 stuk", "prijs p/s bij 2", "korting bij 2 (%)",
                    "prijs p/s bij 3", "korting bij 3 (%)",
                    "pakket normaal", "pakket besparing", "pakket inhoud",
                    "bron"])
        for p in producten:
            for v in p["varianten"]:
                s = dict(v["staffel"])
                w.writerow([
                    v["barcode"], v["code"], nette_naam(v["naam"]),
                    "voordeelpakket" if v["is_pakket"] else "artikel",
                    f"{v['adviesprijs']:.2f}".replace(".", ","),
                    f"{v['prijs']:.2f}".replace(".", ","),
                    f"{s[2]:.2f}".replace(".", ",") if 2 in s else "",
                    f"{korting_pct(v['prijs'], s[2]):.1f}".replace(".", ",") if 2 in s else "",
                    f"{s[3]:.2f}".replace(".", ",") if 3 in s else "",
                    f"{korting_pct(v['prijs'], s[3]):.1f}".replace(".", ",") if 3 in s else "",
                    f"{v['pakket_normaal']:.2f}".replace(".", ",") if v["is_pakket"] else "",
                    f"{v['pakket_besparing']:.2f}".replace(".", ",") if v["is_pakket"] else "",
                    pakket_tekst(v["pakket_inhoud"]) if v["is_pakket"] else "",
                    p["url"],
                ])
    print(f"Staffeloverzicht geschreven: {pad}")


def save_xml(root, filepath):
    xml_str = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(xml_str).toprettyxml(indent="  ")
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nXML opgeslagen: {filepath}")


def main():
    print("Alka UPDATE-feed gestart\n")
    start = time.time()
    tel = ac.TelStand()
    producten = ac.fetch_products(tel)
    varianten = ac.controleer(producten, tel)

    save_xml(build_xml(producten), OUTPUT_FILE)
    schrijf_staffel_csv(producten)

    met_staffel = sum(1 for p in producten for v in p["varianten"] if v["staffel"])
    uit_voorraad = sum(len(p["varianten"]) for p in producten if not p["op_voorraad"])
    print(f"\nKlaar in {time.time() - start:.0f}s")
    print(f"  {tel.regel()}")
    print(f"  {varianten} regels in de feed, {met_staffel} met een staffelkorting, "
          f"{uit_voorraad} niet leverbaar")
    print(f"\nFeed-URL voor Stock Sync (Update):\n{FEED_URL}")


if __name__ == "__main__":
    main()
