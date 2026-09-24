# Pump foil DK

Kort over pumpfoil-spots i Danmark. Brugeren skriver dansk. Svar på dansk.

- Kilden er Google-regnearket (fanen "Spots"), som er udgivet som CSV (`config.json` → `sheet_csv_url`).
  `data/spots.csv` er en kopi. Ret aldrig kun i kopien, hvis arket er sat op, for så overskrives den i nat.
- To output: `index.html` (web-kortet på GitHub Pages, læser arket live) og `dist/pumpfoil-dk.kml`
  (importeres manuelt i Google My Maps, som ikke har nogen API).
- "Opdater My Maps-filen" betyder: `python3 tools/build_mymaps_kml.py`, commit `data/spots.csv` og
  `dist/pumpfoil-dk.kml`, push. Fortæl hvor mange spots der kom med, og om nogen manglede koordinater.
- KML-formatet efterligner My Maps' egen eksport: style-id'er `icon-1880-<farve>[-nodesc]` og
  `gx_media_links`. Rør ikke ved det uden at teste en import. Round-trip-test:
  `python3 tools/kml_to_csv.py dist/pumpfoil-dk.kml /tmp/rt.csv` og sammenlign med `data/spots.csv`.
- Apps Script-tests: `node apps-script/test.mjs`.
- Billeder hostet i My Maps (`mymaps.usercontent.google.com`) kan ikke vises på andre sider (CORP), så
  web-kortet viser dem som links.

## Kandidat-kartoteket (tools/kandidater/)

"Fortsæt gennemgangen af kandidater" betyder:
1. `python3 tools/kandidater/review.py status`, derefter `next --min-score 2 -n 40` (evt. `--bbox syd,vest,nord,øst`
   for én landsdel ad gangen). Tag de højeste scorer først. Score 1–1,5 (en enkelt bro uden andre OSM-tags,
   typisk private broer) kommer til sidst.
2. `review.py render ID …`, 8–10 ad gangen. Se på hvert billede med Read. Højre halvdel er nærbilledet i
   zoom 18 med et pixel-rutenet (hver streg = 100 px ≈ 30 m). Stiplede linjer er OSM: magenta = bro,
   cyan = flydebro, orange = andet.
   Steder uden bro (kun `badested`) kan tjekkes 6 ad gangen med `review.py sheet ID …`.
3. Skriv en JSONL-fil med én linje pr. sted: `{"id", "vurdering", "type", "px": [x, y], "begrundelse"}` og kør
   `review.py apply fil.jsonl`. `px` er broens/pontonens yderste ende i skærmbilledet og bliver til
   koordinater. Udelad `px` ved "nej".
4. Commit `data/kandidater.csv` og `data/kandidater-log.csv` løbende.

Kriterier (luftfotoet viser ikke broens højde, så vær ærlig om det i begrundelsen):
- **lovende**: bro, flydebro eller ponton ud til mørkt (dybt) vand. Mindst ca. 50×50 m frit vand, roligt
  (sø, beskyttet bassin eller læ) og offentlig adgang (badested, klub, park).
- **måske**: noget væsentligt er uklart eller trækker ned, fx lavt vand eller ålegræs, åben kyst med bølger,
  strøm, bådtrafik, mulig privat adgang, eller et gammelt eller vinterbillede.
- **nej**: ingen bro, tæt pakket lystbådehavn, smal å eller kanal (under ca. 50 m) med strøm, færgeleje,
  privat eller for lille, eller fejl i OSM-søgningen (padel, vejnavne, ruter …). Skriv altid hvorfor.
- Gudenåen har strøm og kanotrafik: kun "måske", hvis den er bred (over ca. 80 m).
- Rettes et søgefilter i `find.py`, så kør `find.py` igen. Vurderinger bevares.

Promote til kortet (`review.py promote`) kun når brugeren beder om det.
