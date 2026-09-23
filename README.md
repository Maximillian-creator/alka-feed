# Alka® feeds → Stock Sync

Haalt de catalogus van **Alka®** (`alka.nl`) op en maakt twee XML-feeds voor
[Stock Sync](https://stock-sync.com), plus twee leesbare CSV's. Alles publiek:
geen login, geen sleutel, geen CAPTCHA. Hun API staat uit (`/api-not-enabled`),
dus de gegevens komen uit de HTML van de productpagina's (Sylius-winkel).

| Feed | Script | Output | Doel | Schema |
|---|---|---|---|---|
| **Update-feed** | `scraper.py` | `alka_feed.xml` | Prijs + beschikbaarheid van **bestaande** producten | 2× per dag (05:20 + 17:20 UTC) |
| **Add-feed** | `add_scraper.py` | `alka_add_feed.xml` | **Nieuwe** producten aanmaken met álle info | 1× per week (ma 03:20 UTC) |
| Staffeloverzicht | `scraper.py` | `alka_staffelkortingen.csv` | De bundelkortingen om naast de inkoop te leggen | met de update-feed |
| Tekstbron | `add_scraper.py` | `alka_tekstbron.csv` | Waar elke tekst vandaan komt, per variant | met de add-feed |
| Koppelvoorstel | `koppeling.py` | `alka_koppeling.csv` | Onze winkel naast de feed leggen | eenmalig, met de hand |
| Barcodes | `koppeling.py` | `alka_barcodes.csv` | De 21 varianten die klaarstaan om gezet te worden | idem |
| Uitbreiding | `koppeling.py` | `alka_uitbreiding.csv` | Wat Alka voert en wij (nog) niet | idem |

## Feed-URL's (Stock Sync)

```
Update:  https://raw.githubusercontent.com/Maximillian-creator/alka-feed/main/alka_feed.xml
Add:     https://raw.githubusercontent.com/Maximillian-creator/alka-feed/main/alka_add_feed.xml
```

## Nulmeting 09-09-2026

- 33 product-URL's in `sitemap.xml`; daarvan geeft er **één 404**
  (`alka-onderzetters`, staat nog in hun sitemap) en slaan wij er **één** over
  (`alka-product-sample`, een voorbeeldpotje van Alka zelf).
- **31 pagina's, 50 varianten**: 41 losse artikelen en **9 voordeelpakketten**.
- **22 varianten hebben een staffelkorting**, 28 niet.
- Alles stond op dat moment op voorraad.

## De bundelkorting — twee soorten

Alka doet het op twee manieren, en allebei staan ze in de feed.

### 1. Staffel per artikel (2 en 3 stuks)

Op de productpagina staat een trap: 1 stuk / 2 stuks / 3 stuks, met de prijs
**per stuk**. Bijvoorbeeld BasenCaps Original: € 26,95 → € 25,49 (−5%) →
€ 23,99 (−11%). In de feed:

| Veld | Betekenis |
|---|---|
| `staffel2_prijs` / `staffel3_prijs` | prijs **per stuk** bij 2 resp. 3 stuks |
| `staffel2_korting_pct` / `staffel3_korting_pct` | hoeveel procent goedkoper dan bij 1 stuk |
| `laagste_stuksprijs` + `laagste_stuksprijs_vanaf` | de goedkoopste stuksprijs en vanaf hoeveel stuks |

De percentages zijn **berekend, niet overgenomen**: alka.nl rondt zijn eigen
badge naar beneden af (25,49 van 26,95 is 5,4%, zij tonen −5%). `test_feed.py`
legt de twee naast elkaar en valt om bij meer dan één procentpunt verschil.

De trappen over de hele catalogus (09-09-2026):

| 2 stuks | 3 stuks | artikelen |
|---|---|---|
| geen korting | geen korting | 28 (19 artikelen + de 9 pakketten) |
| −6,4% | −10,8% | 5 |
| −5,4% | −11,0% | 4 |
| −5,0% | −10,0% | 4 |
| −5,7% | −11,0% | 3 |
| −5,9% | −10,5% | 3 |
| overige | | 3 |

> Waar drie keer dezelfde prijs staat (Deo 30ml: 9,95 / 9,95 / 9,95) blijven de
> staffelvelden **leeg**. Een "−0%" in de feed zou een korting suggereren die er
> niet is.

### 2. Voordeelpakketten (9 stuks)

De starterspakketten, huidverzorgingspakketten en geurenpakketten zijn eigen
artikelen met een eigen EAN. Zij krijgen `soort = voordeelpakket` en:

| Veld | Betekenis |
|---|---|
| `price` | de normale prijs van de losse onderdelen samen (bv. € 41,90) |
| `actieprijs` | de pakketprijs (bv. € 37,95) |
| `pakket_normaal` / `pakket_besparing` | wat Alka zelf toont: normaal en besparing |
| `pakket_inhoud` | `1x Alka® BasenCaps Original - 60 capsules (€ 26,95); 1x Alka® Thee - 48 filterzakjes (€ 14,95)` |

Een test controleert dat de inhoud **optelt** tot `pakket_normaal` en dat de
besparing het verschil met de pakketprijs is. Klopt dat niet, dan is er iets
veranderd aan hun pagina en niet aan onze rekensom.

> **Dit is de consumentenkorting van alka.nl, geen inkoopafspraak.** Wat wij bij
> Alka betalen ligt niet vast in dit project, dus er staat **geen kostprijs** in
> de feed. Zodra de inkoopcondities bekend zijn, is dat één regel in
> `scraper.py`. `alka_staffelkortingen.csv` is er om die twee naast elkaar te
> kunnen leggen.

## Prijs: adviesprijs of dagprijs?

| Veld | Betekenis |
|---|---|
| `price` | adviesprijs — de doorgestreepte prijs op de pagina |
| `actieprijs` | wat alka.nl vandaag vraagt voor 1 stuk |

Bij tien artikelen verschillen die twee: de negen pakketten en de
**Zuur-base 30 dagen kuur** (advies € 66,85, vandaag € 59,95).

> Map standaard **`price`** op de verkoopprijs. Wie `actieprijs` mapt, neemt de
> tijdelijke acties van de leverancier over in de eigen winkel — inclusief het
> moment waarop die actie stopt.

## Voorraad

alka.nl toont alleen "Op voorraad" of niet, **per pagina** (niet per variant) en
zonder aantallen. Daarom levert de feed `available` = `true`/`false` en
`quantity` = altijd `0`.

> **Zet in Stock Sync "niet in feed" op _voorraad 0_, nooit op archiveren of
> concept.** Stock Sync heeft in deze winkel al drie keer een hele
> leverancierscatalogus stilgezet (tot 44 dagen onvindbaar) toen een feed leeg of
> half binnenkwam.

Kan het voorraadmerk op een pagina niet gelezen worden — bijvoorbeeld omdat Alka
zijn thema verandert — dan schrijft de scraper **helemaal geen feed** en meldt
hij welke pagina's het betrof. Een verzonnen voorraadstand is erger dan geen.

Verder stopt de scraper bij minder dan 25 productpagina's of 40 varianten, en
bij twee varianten met dezelfde EAN.

## Eerst koppelen, anders doet de feed niets

**Alle 22 Alka-varianten in onze Shopify hebben een lege SKU én geen barcode**
(peiling 09-09-2026). Stock Sync matcht op SKU of barcode; zijn allebei leeg,
dan vindt hij nul artikelen en gebeurt er niets — zonder foutmelding.

```bash
python scraper.py      # maakt alka_feed.xml
python koppeling.py    # maakt alka_koppeling.csv
```

Stand 10-09-2026: **14 zeker + 7 met de hand nagekeken = 21 klaar** in
`alka_barcodes.csv`. De zeven handmatige beslissingen staan met reden in
`HANDKOPPELING` bovenin `koppeling.py`, zodat een volgende run ze niet opnieuw
hoeft te raden.

Eén artikel blijft over: **Alka® Scrub Pads** (€ 10,75, luffa-sponzen). Die staat
niet meer tussen de 50 varianten van alka.nl. Navragen bij de vertegenwoordiger:
nog leverbaar, of uitfaseren?

Let ook op de kolom `prijsverschil` — wat wij vragen min wat alka.nl vraagt.
Vier varianten staan bij ons **hoger** geprijsd dan bij Alka zelf:

| Ons artikel | Onze prijs | Bij Alka |
|---|---|---|
| Alka Basische Kruiden Thee 48 zakjes | € 16,45 | € 14,95 |
| Alka Basische Kruiden Thee 96 zakjes | € 26,95 | € 24,95 |
| Alka Greens 10 Stuks | € 16,45 | € 14,95 |
| Alka Greens 30 Stuks | € 42,95 | € 39,95 |

Wie `price` klakkeloos mapt, verlaagt daar zijn eigen prijs. Alka verkoopt zelf
aan consumenten, dus boven hun prijs zitten is zichtbaar — maar het blijft een
keuze, geen fout.

Vier handles bevatten een letterlijke `®` (`alka®-scrub-pads`,
`alka®-spermidine-forte`, `alka®-basencaps-calcium`, `alka®-basencaps-magnesium`).
Dat geeft URL's met `%C2%AE`. Wijzigen kan, maar alleen mét redirect.

**Stock Sync → Product Identificeerder = Barcode (EAN).** De variantcode van
Alka (`AV150.1.3.NL`) gaat mee in `sku`, zodat die lege SKU's in dezelfde
beweging gevuld kunnen worden.

## Add-feed: concept-only

`published` staat hard op **false**. De teksten komen letterlijk van alka.nl en
gaan over "zure afvalstoffen", "ontzuren" en "zuur-base balans" — precies waar
EFSA/NVWA/KOAG-KAG over gaan. Themis over deze feed (09-09-2026):
**5 ok, 2 let op, 24 afkeuren**.

```bash
python add_scraper.py
python themis_check.py   # schrijft alka_themis.md
```

Niet meegenomen uit hun pagina's: het blok "Persoonlijk advies" (daar staat het
telefoonnummer van Alka's eigen adviseurs in) en de FAQ (hun retour- en
verzendbeleid). De opmaak wordt gestript; alleen tekstdragende tags blijven.

Wel apart in de feed: `gebruik` (dosering) en `ingredienten` (de tabel met
hoeveelheden en RI%), naast `description`/`body_html`.

## Zelf draaien

```bash
pip install -r requirements.txt

python test_feed.py                          # 13 tests, geen internet nodig
LIVE=1 INSECURE_SSL=1 python test_feed.py    # + drie echte pagina's

INSECURE_SSL=1 python scraper.py             # update-feed
INSECURE_SSL=1 python add_scraper.py         # add-feed
```

`INSECURE_SSL=1` is alleen nodig op de Windows-werkplek (SSL-onderscheppende
proxy). Verder: `MAX_PRODUCTEN=5` om te beperken, `TEST_URL=<url>` voor één
pagina, `ALKA_CACHE=<map>` om opgeslagen HTML te hergebruiken.

## Nog te doen (klikwerk)

1. Repo `alka-feed` aanmaken op GitHub (**publiek**, anders kan Stock Sync de
   raw-URL niet lezen) en deze map pushen.
2. Barcodes uit `alka_koppeling.csv` importeren in Shopify.
3. Stock Sync-taak aanmaken met de update-URL, identificeerder = barcode,
   "niet in feed" = voorraad 0.
4. Pas daarna de add-feed gebruiken — en niets publiceren voordat
   `alka_themis.md` is afgewerkt.
