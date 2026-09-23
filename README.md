# Alka® feeds → Stock Sync

Haalt de catalogus van **Alka®** (`alka.nl`) op en maakt twee XML-feeds voor
[Stock Sync](https://stock-sync.com), plus twee leesbare CSV's. Alles publiek:
geen login, geen sleutel, geen CAPTCHA. Hun API staat uit (`/api-not-enabled`),
dus de gegevens komen uit de HTML van de productpagina's (Sylius-winkel).

| Feed | Script | Output | Doel | Schema |
|---|---|---|---|---|
| **Update-feed** | `scraper.py` | `alka_feed.xml` | Prijs + beschikbaarheid van **bestaande** producten | 2× per dag (05:20 + 17:20 UTC) |
| **Add-feed** | `add_scraper.py` | `alka_add_feed.xml` | **Nieuwe** producten aanmaken met álle info (alle 50) | 1× per week (ma 03:20 UTC) |
| **Add-feed (alleen nieuw)** | `add_scraper.py` | `alka_add_feed_nieuw.xml` | Alleen wat wij nog NIET voeren — 28 regels | idem |
| Staffeloverzicht | `scraper.py` | `alka_staffelkortingen.csv` | De bundelkortingen om naast de inkoop te leggen | met de update-feed |
| Tekstbron | `add_scraper.py` | `alka_tekstbron.csv` | Waar elke tekst vandaan komt, per variant | met de add-feed |
| Koppelvoorstel | `koppeling.py` | `alka_koppeling.csv` | Onze winkel naast de feed leggen | eenmalig, met de hand |
| Barcodes | `koppeling.py` | `alka_barcodes.csv` | De 21 varianten die klaarstaan om gezet te worden | idem |
| Uitbreiding | `koppeling.py` | `alka_uitbreiding.csv` | Wat Alka voert en wij (nog) niet | idem |

## Feed-URL's (Stock Sync)

```
Update:      https://raw.githubusercontent.com/Maximillian-creator/alka-feed/main/alka_feed.xml
Add (nieuw): https://raw.githubusercontent.com/Maximillian-creator/alka-feed/main/alka_add_feed_nieuw.xml
Add (alles): https://raw.githubusercontent.com/Maximillian-creator/alka-feed/main/alka_add_feed.xml
```

> Gebruik voor Stock Sync **`alka_add_feed_nieuw.xml`**. De volledige add-feed
> bevat ook de 22 artikelen die al in de winkel staan; een taak die velden
> bijwerkt zou onze eigen teksten overschrijven met die van Alka - en die zijn
> door Themis afgekeurd. Welke EAN's al bezet zijn staat in `alka_in_winkel.txt`,
> geschreven door `koppeling.py` (die scant de héle winkel, dus ook concepten:
> Vliesmaskers stond er als concept in en zou anders dubbel zijn aangemaakt).

## Afbeeldingen per EAN

Alka koppelt zijn foto's aan variantcodes (`sylius-image-variants` in de
galerij). Beide feeds geven daarom **per variant de juiste foto's** mee in
`image` (de hoofdfoto) en `image_links` (alle, komma-gescheiden): elke Deo-geur
krijgt zijn eigen flesje, niet vijf keer hetzelfde plaatje. Heeft een variant
geen eigen foto's, dan die van de productpagina, met de voorkant eerst.

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

## Koppelen: gedaan op 23-09-2026

Stock Sync matcht op SKU of barcode. Stand nu, gemeten via de Admin API:

- **17 varianten hebben hun EAN en variantcode gekregen** (`barcodes_zetten.py`,
  logboek in `alka_barcodes_gezet.csv`).
- **4 varianten hadden al een barcode, en een andere dan Alka opgeeft.** Die zijn
  bewust NIET overschreven. Het zijn de Thee (48 en 96 zakjes) en de Greens (10
  en 30 sticks). Hun EAN's komen op geen enkele Alka-site voor - niet op alka.nl,
  niet op alka.be, niet op alka.eu. Het zijn dus **vorige productversies**; Alka
  voert nu "Greens Multi+" en een vernieuwde thee, en vraagt er minder voor:

  | Ons artikel | Onze EAN | Onze prijs | Alka nu | EAN nu | Adviesprijs |
  |---|---|---|---|---|---|
  | Thee 48 zakjes | 8718546783241 | € 16,45 | Thee - 48 filterzakjes | 8718546783029 | € 14,95 |
  | Thee 96 zakjes | 8718546783449 | € 26,95 | Thee - 96 filterzakjes | 8718546783050 | € 24,95 |
  | Greens 10 Stuks | 8718546784125 | € 16,45 | Greens Multi+ 10 sticks 80g | 8718546784262 | € 14,95 |
  | Greens 30 Stuks | 8718546784040 | € 42,95 | Greens Multi+ 30 sticks 240g | 8718546784309 | € 39,95 |

  Zolang die vier op de oude EAN staan, raakt de feed ze niet aan. Dat is
  voorlopig de veilige stand: pas als vaststaat welke versie er in het magazijn
  ligt, hoort daar een keuze gemaakt te worden.

> **De publieke `products.json` geeft `barcode` niet vrij.** Op 09-09-2026 leidde
> dat tot de conclusie "alle 22 varianten hebben geen barcode". Dat was fout: er
> waren er vier gevuld. `koppeling.py` meet nu via de Admin API en zegt het
> erbij wanneer dat niet lukt.

**Stock Sync → Product Identificeerder = Barcode (EAN).** De variantcode van
Alka (`AV150.1.3.NL`) staat nu ook als `sku` in de winkel.

### Toegang tot Shopify

Er hoeft **geen** `shpat_`-token te bestaan en er mag er zeker geen nieuw
gemaakt of geroteerd worden: dat zou Vega, Sirius, Gaia en Atlas op de VPS
stilzetten. `barcodes_zetten.py` haalt net als de andere agents zelf een token
op met `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET` (client_credentials-grant,
zie `gfy-orderdata.shopify_token_client_credentials`). Die staan in
`gfy-gaia/.env` en de app heeft `write_products`.

```bash
python koppeling.py                    # meet de winkel, schrijft het voorstel
python barcodes_zetten.py              # droogloop
python barcodes_zetten.py --doen       # schrijft, slaat conflicten over
```

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
