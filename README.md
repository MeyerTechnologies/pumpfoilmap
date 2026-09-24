# Pump foil DK 🤙🏻

Kort over pumpfoil-spots i Danmark. Ét Google-regneark er kilden, og ud fra det laves to kort:

```
Google Form ──► Regneark, fanen "Spots" ──┬──► Web-kortet (index.html læser arket direkte)
  Apps Script lægger svar ind som kladde  │     https://meyertechnologies.github.io/pumpfoilmap/
  og sender dig en mail                   │
                                          └──► dist/pumpfoil-dk.kml ──► Google My Maps
                                               (bygges automatisk hver nat)   (listen i Google Maps-appen)
```

Du vedligeholder kun regnearket. Emoji-præfikset ("✅ 🚢 Dockstart - …"), ikonfarverne og
rækkefølgen i My Maps laves automatisk ud fra kolonnerne `status` og `start`.

## Daglig brug

**Nyt spot indsendt:** Du får en mail. Rækken står gult i arket, fordi den er en kladde. Tjek placeringen
(der er et link i mailen), ret hvad der skal rettes, og sæt flueben i `vis`. Web-kortet viser spottet
inden for ca. 5 minutter. Så længe det tager Google at opdatere et udgivet ark.

**Indmeldinger fra kortet:** Klikker man på et gult spot (ikke testet) på web-kortet, står der "Har du været her?"
med knapperne *Det virker / Virker ikke / Andet* og et felt til kommentar. Andre spots har knappen *Foreslå ændring*.
Indmeldingen sendes direkte til Google Formen som "Ændring til eksisterende spot" med spottets id i klammer,
fx `Fussing Sø [fussing-soe]`, så formular-scriptet finder den rigtige række. Feltnumrene står i
`config.json` → `feedback_form`. Ændrer du spørgsmålene i formularen, skal numrene opdateres.

**Ændringsforslag:** Du får en mail, og spottets række bliver orange med forslaget som note på navnet.
Hold musen over navnet for at se forslaget. Ret cellerne, og fjern den orange farve.

**Selv tilføje eller rette:** Skriv direkte i arket. Koordinater får du ved at højreklikke i Google Maps og
klikke på tallene øverst, så kopieres fx `56.1029787, 9.7835161`. Du kan også indsætte et Google Maps-link
i `koordinater`, markere rækken og vælge menuen **Pumpfoil → Find koordinater for markerede rækker**.

**Opdater My Maps**, når du har lyst, fx en gang om ugen:

1. Hent den nyeste fil: [dist/pumpfoil-dk.kml](dist/pumpfoil-dk.kml) → knappen "Download raw file".
   Den bygges hver nat ud fra regnearket. Vil du have den med det samme: fanen *Actions* →
   *Byg My Maps-fil* → *Run workflow*. Du kan også køre `python3 tools/build_mymaps_kml.py` lokalt.
2. Åbn kortet i My Maps → laget **Pumpfoil** → ⋮ → **Genimporter og flet** → **Erstat alle elementer** →
   vælg filen.

## Kolonner i fanen "Spots"

| Kolonne | Indhold |
|---|---|
| `id` | Fast id, bruges i delbare links (`…/pumpfoilmap/#knudhule-badebro`). Laves automatisk. |
| `vis` | Flueben = vises på kortene. Nye indsendelser starter uden flueben. |
| `navn` | Spottets navn uden emoji, fx `Knudhule badebro`. |
| `status` | `Virker`, `Ikke testet` eller `Virker ikke` (grøn, gul, rød). |
| `start` | `Dock`, `Rock`, `Jump`, `Beach` eller `Andet`. |
| `koordinater` | `breddegrad, længdegrad`, som Google Maps kopierer dem. |
| `beskrivelse` | Fri tekst. En linje der ender med kolon (fx `Bundforhold:`) bliver en overskrift. |
| `medier` | Links til billeder og YouTube-videoer. Ét link pr. linje. |
| `opdateret` | Dato. Vises på web-kortet. |
| `note` | Interne noter, fx "tjek placeringen". Vises ikke på kortene. |

Kontaktinfo fra formularen gemmes kun som cellenote på navnet. Noter kommer ikke med, når fanen udgives.

## Engangsopsætning

### 1. Regnearket
1. I Google Formen: **Svar → Link til Sheets**, hvis den ikke allerede er koblet til et regneark.
2. Åbn regnearket → **Filer → Importér → Upload** → vælg `data/spots.csv` → **Indsæt nye ark**.
3. Omdøb den nye fane til **Spots**.

### 2. Formularen
De fire spørgsmål du har i forvejen, beholder du. Tilføj disse fire. Titlerne skal være præcis sådan,
ellers skal du rette dem i `CONFIG.QUESTIONS` øverst i `apps-script/Code.gs`:

| Titel | Type | Svarmuligheder / hjælpetekst |
|---|---|---|
| `Placering` | Kort svar | "Indsæt et link fra Google Maps eller koordinater (højreklik på stedet i Google Maps og klik på tallene)" |
| `Starttype` | Multiple choice | Dockstart · Rockstart · Jumpstart · Beachstart · Andet |
| `Er spottet testet?` | Multiple choice | Ja, det virker · Ikke testet · Ja, men det virker ikke |
| `Billeder eller video` | Kort svar | "Link til billeder eller YouTube (valgfrit)" |

Scriptet virker også uden de nye spørgsmål. Så leder det efter placeringen ud fra spottets navn,
og det er mindre præcist.

### 3. Formular-scriptet
1. I regnearket: **Udvidelser → Apps Script**.
2. Slet indholdet i `Code.gs`, og indsæt indholdet af [apps-script/Code.gs](apps-script/Code.gs). Gem.
3. Vælg funktionen **installer** i menuen øverst, og klik **Kør**. Godkend adgangen. Google advarer, fordi
   scriptet er dit eget og ikke "verificeret": klik **Avanceret → Gå til … (usikkert)**.
4. Genindlæs regnearket. Nu er der en **Pumpfoil**-menu, og nye formular-svar lander i "Spots".

### 4. Udgiv fanen "Spots"
1. **Filer → Del → Udgiv på nettet**.
2. Vælg **kun fanen "Spots"**, ikke "Hele dokumentet", og vælg formatet
   **Kommaseparerede værdier (.csv)** → **Udgiv**. Fanen med formularsvar indeholder kontaktinfo og skal
   ikke udgives.
3. Kopiér linket ind i `config.json` → `sheet_csv_url`, og commit. Fra nu af læser web-kortet og
   KML-byggeren direkte fra arket.

### 5. Web-kortet på Google Sites
Kortet ligger på https://meyertechnologies.github.io/pumpfoilmap/. I Google Sites: **Indsæt → Integrer →
Via URL** → indsæt linket. Du kan også indsætte det som kode:

```html
<iframe src="https://meyertechnologies.github.io/pumpfoilmap/" style="width:100%;height:720px;border:0" allow="geolocation"></iframe>
```

### 6. My Maps første gang
Laget skal være oprettet ved import, før **Genimporter og flet** virker. Test derfor først:

1. **Test på et tomt kort:** My Maps → **Opret et nyt kort** → **Importér** → `dist/pumpfoil-dk.kml`.
   Tjek ikoner, farver, beskrivelser og at billeder og videoer er med.
2. **I det rigtige kort:** **Tilføj lag → Importér** → samme fil. Skjul det gamle lag "Pumpfoil", og
   omdøb det nye til "Pumpfoil". Kortets link er det samme, så Google Sites og delte links virker stadig.
3. Slet først det gamle lag, når billederne er flyttet ud af My Maps (se nedenfor), og alt ser rigtigt ud.

## Kandidat-kartotek: nye steder fra OpenStreetMap

Et system der finder potentielle pumpfoil-steder og husker alt, hvad der er overvejet, også det der er afvist.
Oversigt på kort: https://meyertechnologies.github.io/pumpfoilmap/kandidater.html

1. **Find** (kode): `python3 tools/kandidater/find.py --hent` henter alle broer, flydebroer, badesteder, havnebade,
   vinterbadeklubber, kajak-, kano- og roklubber, marinaer og slæbesteder i Danmark fra OpenStreetMap.
   Objekter inden for 120 m af hinanden samles til ét *sted*. Et sted inden for 250 m af et eksisterende spot
   markeres "på kortet". Hvert sted får en score efter, hvor lovende det ser ud på papiret: flydebro 5,
   kajak-/roklub 4, badebro/vinterbad/havnebad 3, badested 2, almindelig bro/havn/slæbested 1.
2. **Vurdér** (menneske eller Claude): `review.py render` tager et skærmbillede af hvert sted med luftfoto og
   OSM-omrids. Stedet vurderes, og nålen sættes præcist på broen. Se kriterierne i `CLAUDE.md`.
3. **Vand og regler**: `vand.py` kobler EU's officielle badevandsdata på hvert sted (klassifikation fra kommunernes
   målinger) og kendte forhold fra `data/badevand/kendte-forhold*.csv`, fx badeforbud, alger og vildtreservater.
   Steder uden officielt badevand undersøges manuelt (kommunens side, havnens regler …), og kilden noteres.
4. **Godkend på kandidatkortet**: en side på claude.ai (kun for dig), hvor du for hvert sted vælger *Med på kortet*
   eller *Ikke med* samt status (Virker / Ikke testet / Virker ikke) og starttype. Sig "synk kandidatkortet" til
   Claude, så kommer de valgte steder på web-kortet og i My Maps-filen.

**Kartoteket** er `data/kandidater.csv`, med ét sted pr. række:

| Kolonne | Indhold |
|---|---|
| `vurdering` | `lovende`, `måske`, `nej`, `på kortet` eller tom (ikke vurderet endnu) |
| `vand`, `vand_note`, `badevand` | Vandkvalitet og regler: `ok`, `tvivl`, `nej` eller `ukendt`, med noter og kilder |
| `type` | flydebro, ponton, badebro, bro, slæbested, strand, andet |
| `koordinater` | Præcis placering sat ved vurderingen (fx broens yderste ende) |
| `begrundelse` | Hvorfor stedet er vurderet sådan. Står der "nej", kan man se hvorfor senere |
| `kategorier`, `score`, `osm` | Hvad OSM ved om stedet |
| `auto_koordinater` | Stedets midtpunkt ifølge OSM. Bruges til at genkende stedet ved næste kørsel |
| `osm_status` | `forsvundet` = findes ikke længere i søgningen (slettet i OSM eller sorteret fra) |

Intet slettes. En ny kørsel af `find.py` beholder alle vurderinger og tilføjer kun nye steder.
**Loggen** `data/kandidater-log.csv` har én linje pr. kørsel og pr. ændring (tidspunkt, sted, fra → til).

`data/osm/raw.json` (OSM-rådata) og `tools/kandidater/.screens/` (skærmbilleder) er ikke med i git.
Skærmbillederne kræver Google Chrome og Node.

## Billeder
De eksisterende billeder ligger i My Maps. Google tillader ikke, at de vises på andre sider, så web-kortet
viser dem som et link. På sigt bør de flyttes til mappen `media/` i dette repo, som komprimerede JPEG'er,
og linkes derfra. Så virker de begge steder og er ikke afhængige af det gamle My Maps-lag.

## Filer

| Fil | Hvad |
|---|---|
| `index.html` | Web-kortet: Leaflet og OpenStreetMap, ingen build, ingen API-nøgler. |
| `config.json` | Links til regneark, formular og My Maps. |
| `data/spots.csv` | Kopi af regnearket. Backup og reserve, hvis arket ikke kan nås. Opdateres hver nat. |
| `data/mymaps-beskrivelse.txt` | Kortbeskrivelsen og symbolforklaringen i My Maps. |
| `dist/pumpfoil-dk.kml` | Filen du importerer i My Maps. |
| `tools/build_mymaps_kml.py` | Bygger KML-filen. Kun Python, ingen pakker. |
| `tools/kml_to_csv.py` | Engangskonvertering af en My Maps-eksport til `spots.csv`. |
| `apps-script/Code.gs` | Formular-scriptet. `node apps-script/test.mjs` tester det lokalt. |
| `kandidater.html` | Kort over kandidat-kartoteket. |
| `data/kandidater.csv`, `data/kandidater-log.csv` | Kandidat-kartoteket og loggen over alle ændringer. |
| `tools/kandidater/` | `find.py` (find steder i OSM), `review.py` (skærmbilleder, vurdering, promote). |

Lokal forhåndsvisning: `python3 -m http.server` og åbn http://localhost:8000.
