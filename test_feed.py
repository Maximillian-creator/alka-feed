"""
Tests bij de Alka-feed
======================
Elk getal dat de feed afdrukt moet betekenen wat zijn etiket zegt. Deze tests
pinnen dat vast op nagebouwde HTML uit alka.nl (letterlijk overgenomen markup,
09-09-2026), zodat ze overal draaien - ook in GitHub Actions zonder internet:

  1. de staffel: 2 en 3 stuks, prijs per stuk, en dat drie keer dezelfde prijs
     géén korting is;
  2. het kortingspercentage tegenover de badge die alka.nl zelf toont;
  3. adviesprijs versus dagprijs (de 30-dagenkuur staat afgeprijsd);
  4. het voordeelpakket: inhoud telt op tot de normale prijs, besparing klopt;
  5. de sloten: geen EAN, dubbele EAN, onleesbaar voorraadmerk.

Daarnaast een livecontrole op drie echte pagina's (alleen met LIVE=1).

    python test_feed.py
    LIVE=1 INSECURE_SSL=1 python test_feed.py
"""

import os
import re
import sys

import alka_common as ac
from scraper import korting_pct

VOORRAAD_JA = ('<div class="d-flex align-items-center in-stock"><span '
               'class="ball bg-success me-2"></span>Op voorraad. Voor 23:59 uur '
               'besteld = morgen in huis!</div>')
VOORRAAD_NEE = ('<div class="d-flex align-items-center"><span '
                'class="ball bg-danger me-2"></span>Tijdelijk uitverkocht</div>')


def tier_blok(code, ean, naam, origineel, trappen, badges=()):
    """De markup van alka.nl: één tabel per variant, één kolom per aantal."""
    kolommen = []
    for i, (aantal, cent) in enumerate(trappen):
        badge = (f'<span class="text-discount text-discount-tier fw-bold">'
                 f'-{badges[i]}%</span>' if i < len(badges) and badges[i] else "")
        kolommen.append(
            f'<div data-qty="{aantal}" data-price="{cent}" class="col-4 tier-price-col">'
            f'<div class="fw-semibold"><span class="order-1">{aantal} Stuks</span>'
            f'{badge}<span class="price">€ {cent / 100:.2f}</span></div></div>')
    return (f'<div id="{code}_table" data-variant-code="{code}" '
            f'data-variant-ean="{ean}" data-variant-name="{naam}" '
            f'data-variant-original-price="{origineel}" '
            f'data-variant-tierprices="{len(trappen) - 1}" class="my-3">'
            + "".join(kolommen) + "</div>")


def pagina(inhoud, titel="Alka® BasenCaps Original", voorraad=VOORRAAD_JA):
    return (f'<h1 class="me-2">{titel}</h1>'
            f'<h2 class="fw-semibold">Basische capsules</h2>'
            f'{voorraad}<div id="tier_prices_tables">{inhoud}</div>')


BASENCAPS = pagina(tier_blok(
    "AV150.1.3.NL", "8718546781049", "Alka® BasenCaps Original - 60 capsules - NL",
    2695, [(1, 2695), (2, 2549), (3, 2399)], badges=("", "5", "11")))

DEO_30ML = pagina(tier_blok(
    "AV330.1.1.NL", "8718546781278", "Alka® Deo - Original - 30ml - NL",
    995, [(1, 995), (2, 995), (3, 995)]), titel="Alka® Deo")

KUUR = pagina(tier_blok(
    "AV550.1.2.NL", "8718546788284", "Alka® Zuur-base 30 dagen kuur - NL",
    6685, [(1, 5995), (2, 5995), (3, 5995)]), titel="Alka® Zuur-base 30 dagen kuur")

PAKKET = (
    '<h1 class="me-2">Alka® Starterspakket capsules (1-2)</h1>'
    + VOORRAAD_JA +
    '<div class="my-2"><span class="fw-bold">Prijs voordeelpakket € 37,95</span></div>'
    '<div class="mt-2 mb-3"><span class="fw-normal text-discount">'
    '<del>Normaal € 41,90</del></span>'
    '<small class="text-muted ps-2">(besparing € 3,95)</small></div>'
    '<div class="my-2"> 1 x Alka® BasenCaps Original - 60 capsules - NL (€ 26,95) </div>'
    '<div class="my-2"> 1 x Alka® Thee - 48 filterzakjes - NL (€ 14,95) </div>'
    '<div id="bundle_variant" data-variant-code="AV802.NL" '
    'data-variant-ean="8718546782688" '
    'data-variant-name="Alka® Starterspakket capsules (1-2) - NL" '
    'data-variant-original-price="4190" data-variant-price="3795" class="my-3"></div>'
)

URL = "https://www.alka.nl/producten/test-product"


def variant(html, url=URL):
    p = ac.parse_pagina(url, html)
    assert p is not None, "pagina leverde geen product"
    return p, p["varianten"][0]


def test_staffel_is_de_prijs_per_stuk():
    p, v = variant(BASENCAPS)
    assert v["barcode"] == "8718546781049"
    assert v["adviesprijs"] == 26.95 and v["prijs"] == 26.95
    assert v["staffel"] == [(2, 25.49), (3, 23.99)], v["staffel"]
    assert p["op_voorraad"] is True


def test_zelfde_prijs_is_geen_staffelkorting():
    """Deo 30ml kost 9,95 bij 1, 2 én 3 stuks. Dat als '-0%' in de feed zetten
    zou een korting suggereren die er niet is."""
    _, v = variant(DEO_30ML)
    assert v["staffel"] == [], v["staffel"]


def test_kortingspercentage_klopt_met_de_badge_van_alka():
    """Wij rekenen zelf; alka.nl rondt naar beneden af. Meer dan een procentpunt
    verschil betekent dat wij iets anders rekenen dan zij tonen."""
    _, v = variant(BASENCAPS)
    badges = [int(b) for b in re.findall(r"text-discount-tier fw-bold\">-(\d+)%", BASENCAPS)]
    berekend = [korting_pct(v["prijs"], prijs) for _, prijs in v["staffel"]]
    assert len(badges) == len(berekend) == 2, (badges, berekend)
    for eigen, site in zip(berekend, badges):
        assert 0 <= eigen - site <= 1.0, f"eigen {eigen}% vs alka.nl {site}%"


def test_dagprijs_mag_onder_de_adviesprijs_liggen():
    """De 30-dagenkuur staat afgeprijsd: doorgestreept 66,85, vandaag 59,95."""
    _, v = variant(KUUR)
    assert v["adviesprijs"] == 66.85 and v["prijs"] == 59.95


def test_adviesprijs_nooit_onder_de_dagprijs():
    """Zou alka.nl ooit een hogere dagprijs dan 'origineel' tonen, dan blijft
    `price` de hoogste van de twee - anders zet Stock Sync een doorgestreepte
    prijs onder de verkoopprijs."""
    raar = pagina(tier_blok("AV1.NL", "8718546780011", "Test - NL",
                            1000, [(1, 1200)]))
    _, v = variant(raar)
    assert v["adviesprijs"] == 12.00 and v["prijs"] == 12.00


def test_voordeelpakket_telt_op():
    p, v = variant(PAKKET)
    assert v["is_pakket"] is True
    assert v["barcode"] == "8718546782688"
    assert v["prijs"] == 37.95 and v["pakket_normaal"] == 41.90
    assert v["pakket_besparing"] == 3.95
    assert sum(n * prijs for n, _, prijs in v["pakket_inhoud"]) == v["pakket_normaal"]
    assert round(v["pakket_normaal"] - v["prijs"], 2) == v["pakket_besparing"]


def test_zonder_ean_geen_regel():
    """Zonder EAN kan Stock Sync niets matchen; die variant hoort niet in de feed."""
    zonder = pagina(tier_blok("AV1.NL", "", "Test - NL", 1000, [(1, 1000)]))
    assert ac.parse_pagina(URL, zonder) is None


def test_onleesbaar_voorraadmerk_stopt_de_feed():
    """Geen 'nee' verzinnen en geen 'ja' aannemen: de scraper schrijft niets."""
    kaal = BASENCAPS.replace(VOORRAAD_JA, "")
    tel = ac.TelStand()
    p = ac.parse_pagina(URL, kaal, tel)
    assert p["op_voorraad"] is None
    assert tel.voorraad_onbekend == ["test-product"]
    try:
        ac.controleer([p] * 50, tel)
    except SystemExit as e:
        assert "voorraadmerk" in str(e)
    else:
        raise AssertionError("controleer() had moeten stoppen")


def test_uitverkocht_wordt_gelezen():
    p, _ = variant(BASENCAPS.replace(VOORRAAD_JA, VOORRAAD_NEE))
    assert p["op_voorraad"] is False


def test_dubbele_ean_stopt_de_feed():
    p = ac.parse_pagina(URL, BASENCAPS)
    tweede = ac.parse_pagina(URL.replace("test-product", "ander"), BASENCAPS)
    tel = ac.TelStand()
    try:
        ac.controleer([p, tweede] + [p] * 48, tel)
    except SystemExit as e:
        assert "dezelfde EAN" in str(e)
    else:
        raise AssertionError("controleer() had moeten stoppen")


def test_te_weinig_varianten_stopt_de_feed():
    tel = ac.TelStand()
    try:
        ac.controleer([ac.parse_pagina(URL, BASENCAPS)], tel)
    except SystemExit as e:
        assert "ondergrens" in str(e)
    else:
        raise AssertionError("controleer() had moeten stoppen")


def test_optie_zonder_keuzetabel():
    """Eén variant, dus geen keuzetabel op de pagina: het label komt uit de naam,
    zonder de landcode."""
    html = pagina(tier_blok("AV246.1.1.NL", "8718546782466",
                            "Alka® Bitter - 50ml - Original - biologisch - NL",
                            1495, [(1, 1495)]), titel="Alka® Bitter")
    _, v = variant(html)
    assert v["optie"] == "50ml - Original - biologisch", v["optie"]


def test_advies_en_faq_blijven_buiten_de_tekst():
    """Het adviesblok bevat het telefoonnummer van Alka's eigen adviseurs."""
    html = BASENCAPS + (
        '<div id="collapse_description" class="c"><p>Productinformatie.</p></div>'
        '<section><h2 id="heading_advice"></h2></section>'
        '<div id="collapse_advice" class="c"><p>Bel 040 - 304 00 17</p></div>')
    p, _ = variant(html)
    assert "Productinformatie." in p["omschrijving"]
    assert "040" not in p["omschrijving"], p["omschrijving"]


def test_koppeling_overleeft_een_actie_van_de_leverancier():
    """Een actie bij de leverancier mag de koppeling niet slopen.

    Op 23-09-2026 zette Alka de hele catalogus 20% af. De koppeling vergeleek
    toen nog met de dagprijs: 14 regels die "zeker" waren vielen terug naar
    "controleren" en het barcodebestand slonk van 21 naar 7 - terwijl er niets
    mis was. Sindsdien weegt de adviesprijs mee.
    """
    from koppeling import beste
    kandidaten = [
        {"barcode": "8718546781049", "sku": "AV150.1.3.NL",
         "titel": "Alka® BasenCaps Original - 60 capsules",
         "advies": 26.95, "prijs": 21.56, "soort": "artikel", "url": ""},
        {"barcode": "8718546782435", "sku": "AV230.3.1.NL",
         "titel": "Alka® Mineralen - 60 caps",
         "advies": 24.95, "prijs": 19.96, "soort": "artikel", "url": ""},
    ]
    _, naam, prijs_gelijk, k = beste("Alka® BasenCaps Original", 26.95, kandidaten)
    assert k["sku"] == "AV150.1.3.NL", k["titel"]
    assert prijs_gelijk is True, "adviesprijs 26,95 moet blijven tellen"
    assert naam >= 0.6, naam


def test_live():
    """Drie echte pagina's: EAN geldig, prijzen kloppend, staffel oplopend
    goedkoper, en bij een pakket telt de inhoud op tot de normale prijs."""
    for url in [
        "https://www.alka.nl/producten/alka-basencaps-original",
        "https://www.alka.nl/producten/alka-deo",
        "https://www.alka.nl/producten/alka-starterspakket-capsules-1-2",
    ]:
        os.environ["TEST_URL"] = url
        producten = ac.fetch_products()
        assert producten, f"niets geparsed voor {url}"
        for p in producten:
            assert p["op_voorraad"] is not None, f"voorraadmerk onleesbaar: {url}"
            for v in p["varianten"]:
                assert ac.EAN_RE.match(v["barcode"]), f"geen EAN: {v}"
                assert v["prijs"] > 0, f"geen prijs: {v}"
                assert v["adviesprijs"] >= v["prijs"] - 0.005, f"advies onder dag: {v}"
                vorige = v["prijs"]
                for aantal, prijs in v["staffel"]:
                    assert prijs < vorige + 0.005, f"staffel niet goedkoper: {v}"
                    vorige = prijs
                if v["is_pakket"]:
                    som = sum(n * pr for n, _, pr in v["pakket_inhoud"])
                    assert abs(som - v["pakket_normaal"]) < 0.005, \
                        f"inhoud {som} telt niet op tot {v['pakket_normaal']}"
        print(f"  ok: {url.rsplit('/', 1)[-1]}")
    os.environ.pop("TEST_URL", None)


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and (k != "test_live" or os.environ.get("LIVE"))]
    mislukt = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:
            mislukt += 1
            print(f"FOUT {t.__name__}: {e}")
    print(f"\n{len(tests) - mislukt}/{len(tests)} geslaagd")
    if not os.environ.get("LIVE"):
        print("(livecontrole overgeslagen - draai met LIVE=1 INSECURE_SSL=1)")
    return 1 if mislukt else 0


if __name__ == "__main__":
    sys.exit(main())
