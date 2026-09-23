#!/usr/bin/env python3
"""Konverterer en KML-eksport fra Google My Maps til spots.csv (formatet regnearket bruger).

Brug:
    python3 tools/kml_to_csv.py "Pump foil DK.kml" data/spots.csv

Status læses fra ikonfarven (grøn/gul/rød), starttype fra emoji/tekst i navnet.
Emoji-præfikset ("✅ 🚢 Dockstart - ") fjernes fra navnet, fordi kortet selv
tilføjer det ud fra kolonnerne status og start.
"""
import csv
import html
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date

NS = {"k": "http://www.opengis.net/kml/2.2"}

STATUS_BY_COLOR = {"0F9D58": "Virker", "FFD600": "Ikke testet", "A52714": "Virker ikke"}
STATUS_BY_EMOJI = {"✅": "Virker", "❓": "Ikke testet", "⛔": "Virker ikke"}

START_WORDS = [("dock", "Dock"), ("rock", "Rock"), ("jump", "Jump"), ("beach", "Beach")]
START_EMOJI = [("🚢", "Dock"), ("🪨", "Rock"), ("🏃", "Jump"), ("🏖", "Beach")]

PREFIX_RE = re.compile(r"^[^A-Za-zÆØÅæøå0-9]*(?:(?:dock|rock|jump|beach)\s*start)?\s*-?\s*", re.I)
YT_RE = re.compile(r"(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})")


def text(el, tag):
    child = el.find(f"k:{tag}", NS)
    return (child.text or "").strip() if child is not None else ""


def parse_start(name):
    lower = name.lower()
    for word, value in START_WORDS:
        if word in lower:
            return value
    for emoji, value in START_EMOJI:
        if emoji in name:
            return value
    return ""


def normalize_media(url):
    url = html.unescape(url.strip())
    if "img.youtube.com" in url:
        return None  # thumbnail, genereres automatisk ud fra videoen
    yt = YT_RE.search(url)
    if yt:
        return f"https://www.youtube.com/watch?v={yt.group(1)}"
    return url


def clean_description(raw):
    if not raw:
        return ""
    s = re.sub(r"<img[^>]*>", "", raw)
    s = re.sub(r"<a[^>]*>\s*(https?://\S*)?\s*</a>", "", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = "\n".join(line.rstrip() for line in s.splitlines())
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def media_from(pm, raw_desc):
    urls = []
    for data in pm.findall(".//k:Data", NS):
        if data.get("name") == "gx_media_links":
            urls += (data.find("k:value", NS).text or "").split()
    urls += re.findall(r'(?:src|href)="([^"]+)"', raw_desc or "")
    seen, out = set(), []
    for u in urls:
        n = normalize_media(u)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def main(src, dst):
    root = ET.parse(src).getroot()
    rows, used_ids = [], set()
    for pm in root.findall(".//k:Placemark", NS):
        raw_name = text(pm, "name")
        style = text(pm, "styleUrl")
        color = re.search(r"icon-\d+-([0-9A-F]{6})", style)
        status = STATUS_BY_COLOR.get(color.group(1) if color else "", "")
        if not status:
            status = next((v for e, v in STATUS_BY_EMOJI.items() if e in raw_name), "Ikke testet")
        start = parse_start(raw_name)
        name = PREFIX_RE.sub("", raw_name).strip()
        lng, lat = text(pm.find(".//k:Point", NS), "coordinates").split(",")[:2]
        raw_desc = text(pm, "description")

        ascii_name = name.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
        base = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-") or "spot"
        sid, i = base, 2
        while sid in used_ids:
            sid, i = f"{base}-{i}", i + 1
        used_ids.add(sid)

        rows.append({
            "id": sid,
            "vis": "TRUE",
            "navn": name,
            "status": status,
            "start": start,
            "koordinater": f"{float(lat):.7f}, {float(lng):.7f}",
            "beskrivelse": clean_description(raw_desc),
            "medier": "\n".join(media_from(pm, raw_desc)),
            "opdateret": date.today().isoformat(),
            "note": "" if name else "Uden navn i My Maps",
        })

    with open(dst, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} spots skrevet til {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
