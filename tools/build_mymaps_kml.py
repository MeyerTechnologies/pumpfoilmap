#!/usr/bin/env python3
"""Bygger KML-filen til Google My Maps ud fra regnearket.

    python3 tools/build_mymaps_kml.py                      # henter regnearket (config.json → sheet_csv_url)
    python3 tools/build_mymaps_kml.py --source data/spots.csv

Resultat: dist/pumpfoil-dk.kml. Den importeres i My Maps (se README, "Opdater My Maps").

Hentes data fra regnearket, gemmes en kopi i data/spots.csv. Kopien er backup og
reserve for web-kortet, hvis regnearket ikke kan nås.
"""
import argparse
import csv
import html
import io
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Samme ikon og farver som det eksisterende kort, så My Maps viser det præcis som før.
ICON_ID = "1880"
ICON_HREF = "https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png"
STATUS = {  # nøgle: (emoji i navnet, farve i My Maps)
    "virker": ("✅", "0F9D58"),
    "ikke_testet": ("❓", "FFD600"),
    "virker_ikke": ("⛔", "A52714"),
}
START = {  # nøgle: (emoji, tekst i navnet)
    "dock": ("🚢", "Dockstart"),
    "jump": ("🏃🏽‍♀️‍➡️", "Jumpstart"),
    "rock": ("🪨", "Rockstart"),
    "beach": ("🏖️", "Beachstart"),
    "andet": ("📍", ""),
}
SHOW = re.compile(r"^(true|sand|ja|yes|x|1|✓|✔|☑)$", re.I)
YT_RE = re.compile(r"(?:youtube\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")


def status_key(value):
    s = (value or "").strip().lower()
    if not s or "ikke test" in s or "utestet" in s:
        return "ikke_testet"
    if "ikke" in s:
        return "virker_ikke"
    if "virk" in s or "fung" in s or "god" in s:
        return "virker"
    return "ikke_testet"


def start_key(value):
    s = (value or "").strip().lower()
    for key in ("dock", "rock", "jump", "beach"):
        if key in s:
            return key
    return "beach" if "strand" in s else "andet"


def parse_coords(value):
    """'56.1029, 9.7835' (som Google Maps kopierer) eller dansk decimalkomma '56,1029 9,7835'."""
    s = value or ""
    nums = re.findall(r"-?\d{1,3}\.\d+", s)
    if len(nums) < 2:
        nums = [n.replace(",", ".") for n in re.findall(r"-?\d{1,3},\d+", s)]
    if len(nums) < 2:
        return None
    lat, lng = float(nums[0]), float(nums[1])
    return (lat, lng) if abs(lat) <= 90 and abs(lng) <= 180 else None


def my_maps_media(url):
    yt = YT_RE.search(url)
    return f"https://www.youtube.com/embed/{yt.group(1)}" if yt else url


def load_config():
    path = ROOT / "config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def read_source(source):
    if re.match(r"https?://", source):
        with urllib.request.urlopen(source, timeout=30) as res:
            return res.read().decode("utf-8-sig"), True
    return Path(source).read_text(encoding="utf-8-sig"), False


def cdata(text):
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def text_to_html(text):
    return html.escape(text.strip(), quote=False).replace("\r\n", "\n").replace("\n", "<br>")


def style_blocks():
    out = []
    for _, color in STATUS.values():
        kml_color = "ff" + color[4:6] + color[2:4] + color[0:2]  # KML er aabbggrr
        for variant in ("", "-nodesc"):
            sid = f"icon-{ICON_ID}-{color}{variant}"
            balloon = "\n      <BalloonStyle>\n        <text><![CDATA[<h3>$[name]</h3>]]></text>\n      </BalloonStyle>" if variant else ""
            for state, label_scale in (("normal", 0), ("highlight", 1)):
                out.append(f"""    <Style id="{sid}-{state}">
      <IconStyle>
        <color>{kml_color}</color>
        <scale>1</scale>
        <Icon>
          <href>{ICON_HREF}</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>{label_scale}</scale>
      </LabelStyle>{balloon}
    </Style>""")
            out.append(f"""    <StyleMap id="{sid}">
      <Pair>
        <key>normal</key>
        <styleUrl>#{sid}-normal</styleUrl>
      </Pair>
      <Pair>
        <key>highlight</key>
        <styleUrl>#{sid}-highlight</styleUrl>
      </Pair>
    </StyleMap>""")
    return "\n".join(out)


def placemark(spot):
    st_emoji, color = STATUS[spot["status"]]
    sa_emoji, sa_label = START[spot["start"]]
    name = f"{st_emoji} {sa_emoji} {sa_label} - {spot['navn']}" if sa_label else f"{st_emoji} {sa_emoji} {spot['navn']}"
    lat, lng = spot["pos"]
    desc = text_to_html(spot["beskrivelse"])
    style = f"icon-{ICON_ID}-{color}" + ("" if desc else "-nodesc")
    parts = [f"      <Placemark>\n        <name>{html.escape(name, quote=False)}</name>"]
    if desc:
        parts.append(f"        <description>{cdata(desc)}</description>")
    parts.append(f"        <styleUrl>#{style}</styleUrl>")
    if spot["medier"]:
        links = " ".join(my_maps_media(u) for u in spot["medier"])
        parts.append(f"""        <ExtendedData>
          <Data name="gx_media_links">
            <value>{cdata(links)}</value>
          </Data>
        </ExtendedData>""")
    parts.append(f"""        <Point>
          <coordinates>
            {lng:.7f},{lat:.7f},0
          </coordinates>
        </Point>
      </Placemark>""")
    return "\n".join(parts)


def main():
    config = load_config()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=config.get("sheet_csv_url") or str(ROOT / "data/spots.csv"),
                        help="CSV-fil eller link til det udgivne regneark")
    parser.add_argument("--out", default=str(ROOT / "dist/pumpfoil-dk.kml"))
    parser.add_argument("--no-snapshot", action="store_true", help="gem ikke kopi i data/spots.csv")
    args = parser.parse_args()

    raw, from_web = read_source(args.source)
    rows = list(csv.DictReader(io.StringIO(raw)))
    if rows and "koordinater" not in {k.strip().lower() for k in rows[0]}:
        sys.exit("Fejl: kolonnen 'koordinater' findes ikke. Er det den rigtige fane (Spots)?")

    spots, hidden, missing = [], 0, []
    for i, row in enumerate(rows, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if "vis" in row and not SHOW.match(row["vis"]):
            hidden += 1
            continue
        pos = parse_coords(row.get("koordinater"))
        if not pos:
            missing.append(f"række {i}: {row.get('navn') or '(uden navn)'}")
            continue
        spots.append({
            "row": i,
            "navn": row.get("navn", ""),
            "status": status_key(row.get("status")),
            "start": start_key(row.get("start")),
            "pos": pos,
            "beskrivelse": row.get("beskrivelse", ""),
            "medier": [u for u in re.split(r"\s+", row.get("medier", "")) if re.match(r"https?://", u)],
        })

    # Samme rækkefølge som listen i My Maps: grøn, gul, rød – og derefter starttype.
    status_order, start_order = list(STATUS), list(START)
    spots.sort(key=lambda s: (status_order.index(s["status"]), start_order.index(s["start"]), s["row"]))

    legend_path = ROOT / "data/mymaps-beskrivelse.txt"
    legend = text_to_html(legend_path.read_text(encoding="utf-8")) if legend_path.exists() else ""
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Pump foil DK 🤙🏻</name>
    <description>{cdata(legend)}</description>
{style_blocks()}
    <Folder>
      <name>Pumpfoil</name>
{chr(10).join(placemark(s) for s in spots)}
    </Folder>
  </Document>
</kml>
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(kml, encoding="utf-8")

    if from_web and not args.no_snapshot:
        (ROOT / "data/spots.csv").write_text(raw, encoding="utf-8")

    counts = Counter(s["status"] for s in spots)
    print(f"{len(spots)} spots → {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    print("  " + ", ".join(f"{STATUS[k][0]} {counts.get(k, 0)}" for k in STATUS))
    if hidden:
        print(f"  {hidden} skjult (ikke markeret i kolonnen 'vis')")
    if missing:
        print(f"  {len(missing)} uden gyldige koordinater – ikke med i filen:")
        for m in missing:
            print(f"    {m}")
    if from_web and not args.no_snapshot:
        print("  kopi gemt i data/spots.csv")


if __name__ == "__main__":
    main()
