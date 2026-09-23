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
