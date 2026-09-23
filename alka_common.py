"""
Alka® — gedeelde kern
=====================
alka.nl is een publieke **Sylius**-winkel (Omines-hosting, BitBag-plugins).
Geen login, geen sleutel, geen CAPTCHA. De API is uitgezet
(`/api-not-enabled`), dus alles komt uit de HTML van de productpagina's.

Drie bronnen per pagina:

  1. `sitemap.xml`                      -> alle productpagina's (33 op 09-09-2026)
  2. `#tier_prices_tables`              -> per variant: **variantcode**, **EAN**,
     (blok onder de variantkeuze)          adviesprijs en de **staffelprijzen**
                                           (1 / 2 / 3 stuks, prijs per stuk)
  3. `#bundle_variant` (BitBag-plugin)  -> de voordeelpakketten: pakketprijs,
                                           normale prijs, besparing en inhoud

Wat deze winkel bijzonder maakt:

- **Twee soorten bundelkorting.** (a) Een staffel op bijna elke variant: 2 stuks
  -5%, 3 stuks -11%. (b) Negen samengestelde voordeelpakketten (starterspakketten,
  huidverzorgingspakketten, geurenpakketten) met een eigen EAN en een eigen prijs.
  Allebei staan ze in de feed; zie de velden `staffel*` en `pakket*`.
- **De staffel is van alka.nl zelf** — de kortingstrap die zij aan consumenten
  geven. Het is géén inkoopkorting en géén afspraak van ons. Wat wij bij Alka
  inkopen ligt niet vast in dit project; er staat dus bewust geen kostprijs in
  de feed. Zodra die afspraak bekend is, is dat één regel in `scraper.py`.
- **Adviesprijs en dagprijs verschillen soms.** `data-variant-original-price` is
  de doorgestreepte prijs, de staffelregel bij 1 stuk is wat zij vandaag vragen
  (bv. de 30-dagenkuur: advies 66,85 -> vandaag 59,95).
- **Voorraad is per pagina**, niet per variant, en alleen ja/nee. Kan het
  voorraadmerk niet gelezen worden, dan stopt de scraper (zie `TelStand`);
  liever geen feed dan een verzonnen voorraadstand.

Lokaal testen achter een SSL-onderscheppende proxy: INSECURE_SSL=1.
Eén pagina testen: TEST_URL=<volledige productpagina-url>.
Beperken tijdens ontwikkelen: MAX_PRODUCTEN=5.
Opgeslagen pagina's hergebruiken (geen netwerk): ALKA_CACHE=<map>.
"""

import os
import re
import time
from html import unescape

import requests

BASE_URL = "https://www.alka.nl"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
BRAND = "Alka"
REQUEST_DELAY = 0.4

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GFY-AlkaFeed/1.0)",
    "Accept-Language": "nl-NL,nl;q=0.9",
}

VERIFY_SSL = os.environ.get("INSECURE_SSL") != "1"
if not VERIFY_SSL:
    import urllib3

    urllib3.disable_warnings()

SESSIE = requests.Session()
SESSIE.headers.update(HEADERS)

# Anti-archiveerslot. Stock Sync archiveert wat niet in de feed staat; een halve
# feed is gevaarlijker dan geen feed (drie keer eerder gebeurd, tot 44 dagen
# onvindbaar). Peiling 09-09-2026: 33 productpagina's, 50 varianten.
MIN_PRODUCTPAGINAS = 25
MIN_VARIANTEN = 40

# Pagina's die wél in de sitemap staan maar geen verkoopartikel zijn. Niet stil
# wegfilteren: de scraper drukt af wat hij hier overslaat en waarom.
OVERSLAAN = {
    "alka-product-sample": "voorbeeldpotje van Alka zelf, geen verkoopartikel",
}

EAN_RE = re.compile(r"^[0-9]{8,14}$")

_ATTR_RE = re.compile(r'([a-z0-9\-]+)="([^"]*)"', re.I)
_TIER_OPEN_RE = re.compile(r'<div id="([^"]+)_table"([^>]*)>')
_BUNDLE_OPEN_RE = re.compile(r'<div id="bundle_variant"([^>]*)>')
_QTY_RE = re.compile(r'data-qty="(\d+)" data-price="(\d+)"')
_VOORRAADMERK_RE = re.compile(r'class="ball bg-(\w+)[^"]*"[^>]*></span>\s*([^<]{0,80})')
_RADIO_RE = re.compile(r'data-product-id="([^"]+)"')
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_AFBEELDING_RE = re.compile(r'data-original-image-path="([^"]+)"')
_H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)
_H2_RE = re.compile(r'<h2 class="fw-semibold"[^>]*>(.*?)</h2>', re.S)
_PAKKET_REGEL_RE = re.compile(r"(\d+) x ([^<(]+?)\s*\(€\s*([\d.,]+)\)")
_NORMAAL_RE = re.compile(r"<del>\s*Normaal\s*€\s*([\d.,]+)\s*</del>")
_BESPARING_RE = re.compile(r"besparing\s*€\s*([\d.,]+)")

# Alleen deze accordeon-onderdelen gaan mee als producttekst. `advice` bevat het
# telefoonnummer van Alka's eigen adviseurs en `faq` hun retourbeleid - dat hoort
# niet op onze pagina's.
TEKSTSECTIES = {
    "description": "Productinformatie",
    "instructions": "Gebruik",
    "ingredients": "Ingrediënten",
}
TOEGESTANE_TAGS = {"p", "br", "strong", "b", "em", "i", "ul", "ol", "li",
                   "h3", "h4", "h5", "table", "tr", "td", "th", "tbody", "thead"}


class TelStand:
    """Wat de scraper onderweg tegenkwam. Elk getal dat we afdrukken komt
    hiervandaan, zodat 'x varianten' en 'y overgeslagen' optellen tot het aantal
    pagina's dat we echt gezien hebben."""

    def __init__(self):
        self.paginas = 0
        self.overgeslagen = []          # (handle, reden)
        self.verdwenen = []             # in de sitemap, maar de pagina geeft 404
        self.zonder_variant = []        # handles waar niets uit te halen viel
        self.voorraad_onbekend = []     # handles zonder leesbaar voorraadmerk
        self.varianten = 0
        self.pakketten = 0

    def regel(self):
        return (f"{self.paginas} pagina's gelezen, {self.varianten} varianten "
                f"(waarvan {self.pakketten} voordeelpakketten), "
                f"{len(self.overgeslagen)} overgeslagen, "
                f"{len(self.verdwenen)} uit de sitemap verdwenen, "
                f"{len(self.zonder_variant)} zonder variant, "
                f"{len(self.voorraad_onbekend)} zonder leesbaar voorraadmerk")


def _get(url, retries=3):
    cache = os.environ.get("ALKA_CACHE")
    if cache:
        pad = os.path.join(cache, url.rstrip("/").rsplit("/", 1)[-1] + ".html")
        if os.path.exists(pad):
            with open(pad, encoding="utf-8") as f:
                return f.read()
    for poging in range(retries):
        try:
            resp = SESSIE.get(url, timeout=30, verify=VERIFY_SSL)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except requests.HTTPError as e:
            if e.response is not None and 400 <= e.response.status_code < 500:
                raise
            if poging == retries - 1:
                raise
            time.sleep((poging + 1) * 10)
        except Exception:
            if poging == retries - 1:
                raise
            time.sleep((poging + 1) * 10)


def _attrs(fragment):
    return {k.lower(): v for k, v in _ATTR_RE.findall(fragment)}


def _tekst(html):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def _schoon_html(html):
    """Alleen tekstdragende tags overhouden, zonder attributen. De opmaak van
    Alka (achtergrondplaatjes, kolommen, ankers) hoort niet in onze winkel."""
    def bewaar(m):
        sluit, tag = m.group(1), m.group(2).lower()
        return f"<{sluit}{tag}>" if tag in TOEGESTANE_TAGS else " "

    # Een blok kan midden in een tag afgeknipt zijn; die rest hoort er niet bij.
    schoon = re.sub(r"<[^>]*$", "", html or "")
    schoon = re.sub(r"<(/?)([a-zA-Z0-9]+)[^>]*>", bewaar, schoon)
    schoon = re.sub(r"(\s*<br>\s*){3,}", "<br><br>", schoon)
    schoon = re.sub(r"[ \t]+", " ", schoon)
    schoon = re.sub(r"(<p>\s*</p>\s*)+", "", schoon)
    return schoon.strip()


def _prijs(cent):
    return int(cent) / 100.0


def _euro(tekst):
    return float(tekst.replace(".", "").replace(",", "."))


def sitemap_urls():
    """Productpagina's uit sitemap.xml, met /producten in het pad."""
    xml = _get(SITEMAP_URL)
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    prod = [u.strip() for u in urls if "/producten/" in u]
    return sorted(dict.fromkeys(prod))


def _voorraad(flat):
    """True / False / None. None = merk niet herkend; dat is geen 'nee'."""
    merken = _VOORRAADMERK_RE.findall(flat)
    if not merken:
        return None
    kleuren = {kleur for kleur, _ in merken}
    if kleuren == {"success"}:
        return True
    if kleuren & {"danger", "warning", "secondary"}:
        return False
    return None


def _afbeeldingen(flat):
    """(alle, per variantcode, algemeen).

    Alka hangt zijn foto's aan variantcodes: in een `swiper-slide` staat een
    `sylius-image-variants`-blokje met de code erin. Zo hoort
    'Deo-Original-75ml-1-voorkant.jpg' bij AV330.2.1.NL en niet bij de vier
    andere geuren. Slides zonder code zijn sfeer- en USP-beelden die bij het
    hele product horen.

    De galerij staat er twee keer in (grote swiper + duimnagels); elk pad komt
    daarom maar één keer in de lijst, in de volgorde van de pagina.
    """
    alle, per, algemeen = [], {}, []
    for slide in flat.split('<div class="swiper-slide">')[1:]:
        paden = _AFBEELDING_RE.findall(slide)
        if not paden:
            continue
        pad = BASE_URL + paden[0]
        if pad not in alle:
            alle.append(pad)
        # Alleen de codes die VOOR de afbeelding staan. De laatste slide loopt
        # door tot het einde van de pagina, en daar staat het staffelblok met
        # alle variantcodes erin; zonder deze grens zou dat beeld aan elke
        # variant gekoppeld worden.
        kop = slide[:slide.find('data-original-image-path')]
        codes = re.findall(r'data-variant-code="([^"]+)"', kop)
        if codes:
            for code in codes:
                if pad not in per.setdefault(code, []):
                    per[code].append(pad)
        elif pad not in algemeen:
            algemeen.append(pad)
    return alle, per, algemeen


def afbeeldingen_voor(product, variant):
    """De foto's van deze variant: eerst de zijne, dan de algemene van de pagina.

    Heeft de variant geen eigen foto's (de meeste producten hebben er maar één),
    dan zijn het gewoon alle foto's van de pagina - in de volgorde die Alka
    aanhoudt, dus met de voorkant eerst.
    """
    eigen = product.get("afb_per_variant", {}).get(variant["code"], [])
    if not eigen:
        return product["afbeeldingen"]
    return eigen + [p for p in product.get("afb_algemeen", []) if p not in eigen]


def _optielabels(flat):
    """variantcode -> het label uit de variantkeuze ('60 capsules', '75ml')."""
    labels = {}
    for rij in flat.split("<tr")[1:]:
        rij = rij.split("</tr>")[0]
        code = _RADIO_RE.search(rij)
        if not code:
            continue
        cellen = [_tekst(c) for c in _TD_RE.findall(rij)]
        tekst = next((c for c in cellen[1:] if c), "")
        labels[code.group(1)] = tekst
    return labels


def _staffel(tiers):
    """[(aantal, prijs per stuk)] -> alleen de trappen die echt goedkoper zijn.

    De site toont bij sommige artikelen drie keer dezelfde prijs (Deo 30ml:
    9,95 / 9,95 / 9,95). Dat is geen korting en gaat dus ook niet als korting
    de feed in - anders staat er een 0%-staffel die niets betekent.
    """
    if not tiers:
        return []
    basis = tiers[0][1]
    return [(aantal, prijs) for aantal, prijs in tiers[1:] if prijs < basis]


def _teksten(flat):
    """De accordeon-onderdelen die we mogen overnemen, per sleutel."""
    uit = {}
    for sleutel in TEKSTSECTIES:
        start = flat.find(f'id="collapse_{sleutel}"')
        if start < 0:
            continue
        # Voorbij het openingstag zelf, anders komen de attributen als tekst mee.
        start = flat.find(">", start) + 1
        rest = flat[start:]
        eind = rest.find('id="heading_', 10)
        if eind < 0:
            eind = rest.find('<div class="container')
        if eind > 0:
            # `id="heading_x"` staat middenin het openingstag van het VOLGENDE
            # onderdeel; knip bij het begin van dat blok, anders blijft er een
            # halve <h2 ...  aan de tekst hangen.
            grens = max(rest.rfind("<section", 0, eind), rest.rfind("<h2", 0, eind))
            eind = grens if grens > 0 else eind
        blok = rest[:eind if eind > 0 else 20000]
        schoon = _schoon_html(blok)
        if _tekst(schoon):
            uit[sleutel] = schoon
    return uit


def parse_pagina(url, html, tel=None):
    """Eén productpagina -> product-dict, of None als er niets te verkopen valt."""
    handle = url.rstrip("/").rsplit("/", 1)[-1]
    flat = re.sub(r"\s+", " ", html)

    titel = _tekst(_H1_RE.search(flat).group(1)) if _H1_RE.search(flat) else ""
    ondertitel = _tekst(_H2_RE.search(flat).group(1)) if _H2_RE.search(flat) else ""
    afbeeldingen, afb_per_variant, afb_algemeen = _afbeeldingen(flat)
    op_voorraad = _voorraad(flat)
    labels = _optielabels(flat)

    varianten = []

    # (a) gewone varianten met hun staffel
    tier_start = flat.find('id="tier_prices_tables"')
    if tier_start >= 0:
        gebied = flat[tier_start:]
        # Het staffelblok eindigt bij de aantalkiezer; verder zoeken zou
        # data-qty/data-price van heel andere onderdelen kunnen oppikken.
        slot = gebied.find('class="my-3 d-flex flex-row item-quantity')
        if slot > 0:
            gebied = gebied[:slot]
        opens = list(_TIER_OPEN_RE.finditer(gebied))
        for i, m in enumerate(opens):
            eind = opens[i + 1].start() if i + 1 < len(opens) else len(gebied)
            blok = gebied[m.start():eind]
            a = _attrs(m.group(2))
            code = a.get("data-variant-code", "")
            ean = a.get("data-variant-ean", "")
            if not code or not EAN_RE.match(ean):
                continue
            tiers = [(int(q), _prijs(p)) for q, p in _QTY_RE.findall(blok)]
            advies = _prijs(a.get("data-variant-original-price") or 0)
            dagprijs = tiers[0][1] if tiers else advies
            varianten.append({
                "code": code,
                "barcode": ean,
                "naam": _tekst(a.get("data-variant-name", "")),
                "optie": labels.get(code) or _optie_uit_naam(a.get("data-variant-name", ""), titel),
                "adviesprijs": max(advies, dagprijs),
                "prijs": dagprijs,
                "staffel": _staffel(tiers),
                "is_pakket": False,
                "pakket_inhoud": [],
                "pakket_normaal": None,
                "pakket_besparing": None,
            })

    # (b) voordeelpakketten (BitBag product bundle)
    bundle = _BUNDLE_OPEN_RE.search(flat)
    if bundle:
        a = _attrs(bundle.group(1))
        code = a.get("data-variant-code", "")
        ean = a.get("data-variant-ean", "")
        if code and EAN_RE.match(ean):
            prijs = _prijs(a.get("data-variant-price") or 0)
            advies = _prijs(a.get("data-variant-original-price") or 0)
            inhoud = [(int(n), _tekst(naam), _euro(p))
                      for n, naam, p in _PAKKET_REGEL_RE.findall(flat)]
            normaal = _NORMAAL_RE.search(flat)
            besparing = _BESPARING_RE.search(flat)
            varianten.append({
                "code": code,
                "barcode": ean,
                "naam": _tekst(a.get("data-variant-name", "")),
                "optie": "Voordeelpakket",
                "adviesprijs": max(advies, prijs),
                "prijs": prijs,
                "staffel": [],
                "is_pakket": True,
                "pakket_inhoud": inhoud,
                "pakket_normaal": _euro(normaal.group(1)) if normaal else advies,
                "pakket_besparing": _euro(besparing.group(1)) if besparing
                else round(advies - prijs, 2),
            })

    if tel is not None:
        tel.paginas += 1
        if not varianten:
            tel.zonder_variant.append(handle)
        if op_voorraad is None:
            tel.voorraad_onbekend.append(handle)
        tel.varianten += len(varianten)
        tel.pakketten += sum(1 for v in varianten if v["is_pakket"])

    if not varianten:
        return None

    teksten = _teksten(flat)
    return {
        "handle": handle,
        "url": url,
        "titel": titel,
        "ondertitel": ondertitel,
        "afbeeldingen": afbeeldingen,
        "afb_per_variant": afb_per_variant,
        "afb_algemeen": afb_algemeen,
        "teksten": teksten,
        "omschrijving": "\n".join(teksten.get(k, "") for k in TEKSTSECTIES
                                  if teksten.get(k)).strip(),
        "op_voorraad": op_voorraad,
        "varianten": varianten,
    }


def _optie_uit_naam(naam, titel):
    """'Alka® Bitter - 50ml - Original - biologisch - NL' -> '50ml - Original'.

    Alleen gebruikt als de pagina geen variantkeuze toont (één variant); dan is
    er ook geen label om over te nemen.
    """
    naam = _tekst(naam)
    if titel and naam.startswith(titel):
        naam = naam[len(titel):]
    delen = [d.strip() for d in naam.split(" - ") if d.strip()]
    delen = [d for d in delen if d.upper() not in {"NL", "MULTI-LANG", "MULTI"}]
    return " - ".join(delen)


def fetch_products(tel=None):
    """Alle productpagina's ophalen en parsen."""
    tel = tel if tel is not None else TelStand()
    test = os.environ.get("TEST_URL")
    urls = [test] if test else sitemap_urls()
    if not test and len(urls) < MIN_PRODUCTPAGINAS:
        raise SystemExit(
            f"STOP: sitemap gaf {len(urls)} productpagina's (ondergrens "
            f"{MIN_PRODUCTPAGINAS}). Geen feed weggeschreven - een halve feed "
            f"laat Stock Sync producten archiveren."
        )
    limiet = int(os.environ.get("MAX_PRODUCTEN") or 0)
    if limiet:
        urls = urls[:limiet]

    producten = []
    for i, url in enumerate(urls, 1):
        handle = url.rstrip("/").rsplit("/", 1)[-1]
        if handle in OVERSLAAN:
            tel.overgeslagen.append((handle, OVERSLAAN[handle]))
            print(f"  -  overgeslagen: {handle} ({OVERSLAAN[handle]})")
            continue
        try:
            html = _get(url)
        except requests.HTTPError as e:
            # De sitemap van alka.nl loopt achter: op 09-09-2026 stond
            # `alka-onderzetters` er nog in terwijl de pagina 404 geeft.
            if e.response is not None and e.response.status_code == 404:
                tel.verdwenen.append(handle)
                print(f"  !  404, staat nog in de sitemap: {handle}")
                continue
            raise
        p = parse_pagina(url, html, tel)
        if p is None:
            print(f"  !  geen variant gevonden: {handle}")
        else:
            producten.append(p)
            print(f"  {i:>2}/{len(urls)} {handle}: {len(p['varianten'])} variant(en)")
        if not os.environ.get("ALKA_CACHE"):
            time.sleep(REQUEST_DELAY)
    return producten


def controleer(producten, tel):
    """De sloten vóór het wegschrijven. Alles wat hier omvalt is een stille fout
    die anders als een net getal in de winkel zou landen."""
    varianten = sum(len(p["varianten"]) for p in producten)
    if varianten < MIN_VARIANTEN:
        raise SystemExit(
            f"STOP: slechts {varianten} varianten (ondergrens {MIN_VARIANTEN}). "
            f"Geen feed weggeschreven - Stock Sync archiveert wat ontbreekt."
        )
    if tel.voorraad_onbekend:
        raise SystemExit(
            "STOP: op deze pagina's is het voorraadmerk niet herkend: "
            + ", ".join(tel.voorraad_onbekend)
            + ". Waarschijnlijk is het thema van alka.nl gewijzigd. Geen feed "
              "weggeschreven: een verzonnen voorraadstand is erger dan geen."
        )
    ean = {}
    for p in producten:
        for v in p["varianten"]:
            ean.setdefault(v["barcode"], []).append(f"{p['handle']}/{v['code']}")
    dubbel = {k: v for k, v in ean.items() if len(v) > 1}
    if dubbel:
        raise SystemExit(
            "STOP: dezelfde EAN op meer dan één variant: "
            + "; ".join(f"{k}: {', '.join(v)}" for k, v in dubbel.items())
            + ". Stock Sync zou dan de verkeerde prijs op een artikel zetten."
        )
    return varianten
