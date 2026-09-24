#!/usr/bin/env python3
"""Fører beslutningerne fra kandidatkortet (claude.ai) over i kartoteket og på kortet.

    python3 tools/kandidater/sync_beslutninger.py MAPPE [--dry-run]

MAPPE indeholder én JSON-fil pr. beslutning, som ArtifactData 'list' med out_dir gemmer dem
(…/beslutninger/<kandidat-id>.json). En beslutning ser sådan ud:
  {"med": true, "status": "Ikke testet", "start": "Dock", "navn": "Fussing Sø", "note": "…",
   "opdateret": "2026-09-24T14:05:00Z", "synk": {"dato": "…", "spot": "fussing-soe"}}

Med på kortet  → nyt spot i data/spots.csv (eller status/navn/start rettes, hvis det allerede er
                 lagt ind), og kartotekets vurdering bliver 'på kortet'.
Ikke med       → kartotekets vurdering bliver 'nej' med noten som begrundelse. Var stedet allerede
                 lagt på kortet, skjules det (vis = FALSE).
Er regnearket sat op (config.json → sheet_csv_url), skrives rækkerne ud til indsættelse i stedet.

Skriver MAPPE/synk.json med de 'synk'-felter, der skal tilbage i databasen (ArtifactData batch update),
så siden kan vise "Lagt på kortet".
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kartotek import catalog_lock, ROOT, SPOTS_CSV, log, read_catalog, read_csv, today, write_catalog  # noqa: E402

VAND_TEXT = {"ok": "Godt badevand", "tvivl": "Tvivl om vandet eller reglerne", "nej": "Badning frarådes",
             "ukendt": "Ikke undersøgt"}
TYPE_TEXT = {"flydebro": "Flydebro", "ponton": "Ponton", "badebro": "Badebro", "bro": "Bro", "slæbested": "Slæbested",
             "strand": "Strand", "andet": "Startsted"}
CACHE = Path(__file__).resolve().parent / ".cache/adresser.json"
UA = "pumpfoilmap/1.0 (+https://github.com/MeyerTechnologies/pumpfoilmap)"


def address(lat, lon):
    """Adresse via OpenStreetMaps Nominatim (højst 1 opslag pr. sekund, gemmes i en lokal cache)."""
    import time
    import urllib.parse
    import urllib.request
    CACHE.parent.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    key = f"{lat:.5f},{lon:.5f}"
    if key not in cache:
        url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1, "accept-language": "da"})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as res:
                a = json.load(res).get("address", {})
        except Exception:
            a = {}
        time.sleep(1.1)
        road = a.get("road") or a.get("pedestrian") or a.get("path") or a.get("footway") or ""
        street = " ".join(x for x in (road, a.get("house_number", "")) if x)
        town = " ".join(x for x in (a.get("postcode", ""), a.get("city") or a.get("town") or a.get("village")
                                    or a.get("hamlet") or a.get("municipality") or "") if x)
        cache[key] = ", ".join(x for x in (street, town) if x)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache[key]


def source_lines(text):
    """'Note (https://…)' → 'Note\nKilde: https://…' så links virker på kortet."""
    import re
    return re.sub(r"\s*\((https?://[^)\s]+)\)", r"\nKilde: \1", text).strip()


def description(site, d):
    """Beskrivelse i samme opbygning som de eksisterende spots (overskrifter der ender med kolon)."""
    from kartotek import parse_coords
    lat, lon = parse_coords(site["koordinater"] or site["auto_koordinater"])
    navn = (d.get("navn") or site["navn"] or site["område"]).strip()
    osm_navn = site["navn"] if site["navn"] and site["navn"].lower() not in navn.lower() else ""
    parts = [f"Navn på Lokation:\n{navn}" + (f" ({osm_navn})" if osm_navn else "") + f", {site['område']}"]
    adr = address(lat, lon)
    if adr:
        parts.append(f"Adresse:\n{adr}")
    if site["begrundelse"]:
        parts.append(f"Beskrivelse af {TYPE_TEXT.get(site['type'], 'Dock').lower() if site['type'] else 'dock'}:\n"
                     f"{site['begrundelse']}")
    bv = [p.strip() for p in (site["badevand"] or "").split(" · ") if p.strip()]
    officielt = next((p for p in bv if not p.startswith("badevandsprofil") and not p.startswith("Intet officielt")
                      and ":" in p and ("udmærket" in p or "god" in p or "tilfredsstillende" in p or "ringe" in p
                                        or "klassificeret" in p)), "")
    vand = [VAND_TEXT.get(site["vand"], "")]
    if officielt:
        vand.append(f"Officielt EU-badevand: {officielt}.")
    if site["vand_note"]:
        vand.append(source_lines(site["vand_note"]))
    parts.append("Vandkvalitet:\n" + "\n".join(v for v in vand if v))
    regler = [source_lines(p) for p in bv if p is not officielt and not p.startswith("badevandsprofil")
              and not p.startswith("Intet officielt") and p != officielt]
    if regler:
        parts.append("Lokale Regler og Restriktioner:\n" + "\n".join(regler))
    bem = []
    if d.get("note"):
        bem.append(d["note"].strip())
    bem.append("Fundet via luftfoto og OpenStreetMap. Broens højde og vanddybden er ikke målt på stedet – "
               "har du prøvet stedet, så meld gerne ind.")
    parts.append("Andre Bemærkninger:\n" + "\n".join(bem))
    return "\n\n".join(parts)


def utc_now():
    """Samme format som browserens toISOString(), så siden kan sammenligne tidspunkterne."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def slug(text):
    s = text.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    return "-".join("".join(c if c.isalnum() else " " for c in s).split()) or "spot"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mappe")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    files = sorted(Path(args.mappe).rglob("*.json"))
    decisions = {}
    for f in files:
        if f.name == "synk.json":
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        body = doc.get("data", doc)  # ArtifactData gemmer evt. {id, version, data}
        decisions[doc.get("id") or f.stem] = {**body, "_version": doc.get("version")}

    catalog = read_catalog()
    by_id = {s["id"]: s for s in catalog}
    spots = read_csv(SPOTS_CSV)
    fields = list(spots[0].keys())
    spot_by_id = {s["id"]: s for s in spots}
    sheet = bool(json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("sheet_csv_url"))
    synk, report, sheet_rows = [], [], []

    for cid, d in sorted(decisions.items()):
        site = by_id.get(cid)
        if not site or not isinstance(d.get("med"), bool):
            report.append(f"  sprunget over: {cid} (ukendt kandidat eller ingen beslutning)")
            continue
        if d.get("synk") and parse_time(d["synk"].get("dato")) >= parse_time(d.get("opdateret")):
            continue  # allerede synket, ingen ændringer siden
        prev_spot = (d.get("synk") or {}).get("spot") or (site["tæt_på_spot"] if site["vurdering"] == "på kortet" else "")
        spot_id = ""
        if d["med"]:
            navn = (d.get("navn") or site["navn"] or site["område"]).strip()
            row = spot_by_id.get(prev_spot)
            if row:
                spot_id = prev_spot
                row.update({"vis": "TRUE", "navn": navn, "status": d.get("status") or row["status"],
                            "start": d.get("start") or row["start"], "opdateret": today()})
                action = f"rettet {spot_id}"
            else:
                base, i = slug(navn), 2
                spot_id = base
                while spot_id in spot_by_id:
                    spot_id, i = f"{base}-{i}", i + 1
                row = {f: "" for f in fields}
                row.update({
                    "id": spot_id, "vis": "TRUE", "navn": navn, "status": d.get("status") or "Ikke testet",
                    "start": d.get("start") or "Dock", "koordinater": site["koordinater"] or site["auto_koordinater"],
                    "beskrivelse": description(site, d), "opdateret": today(),
                    "note": f"Fra kandidat-kartoteket ({cid})",
                })
                spots.append(row)
                spot_by_id[spot_id] = row
                action = f"nyt spot {spot_id}"
            if sheet:
                sheet_rows.append("\t".join(row[f] for f in fields))
            old = site["vurdering"]
            site["vurdering"], site["tæt_på_spot"], site["vurderet"] = "på kortet", spot_id, today()
            log("beslutning: med", cid, old, "på kortet", f"{action} · {row['status']} · {row['start']}")
            report.append(f"  MED    {cid:<18} → {action} ({row['status']}, {row['start']}) {navn}")
        else:
            row = spot_by_id.get(prev_spot)
            if row:
                row["vis"] = "FALSE"
                spot_id = prev_spot
            old = site["vurdering"]
            reason = d.get("note", "").strip()
            site["vurdering"] = "nej"
            site["begrundelse"] = (f"Fravalgt på kandidatkortet{': ' + reason if reason else ''}. "
                                   f"Min vurdering var: {site['begrundelse']}") if old != "nej" else site["begrundelse"]
            site["vurderet"] = today()
            log("beslutning: ikke med", cid, old, "nej", reason + (f" · spot {spot_id} skjult" if row else ""))
            report.append(f"  IKKE   {cid:<18}" + (f" → spot {spot_id} skjult" if row else "") + (f" · {reason}" if reason else ""))
        synk.append({"op": "update", "collection": "beslutninger", "doc_id": cid,
                     "data": {"synk": {"dato": utc_now(), "spot": spot_id}},
                     **({"if_version": d["_version"]} if d.get("_version") else {})})

    print(f"{len(decisions)} beslutninger læst, {len(synk)} nye/ændrede")
    print("\n".join(report) or "  intet at gøre")
    if args.dry_run:
        print("(dry-run: intet gemt)")
        return
    write_catalog(catalog)
    if sheet:
        print("Regnearket er sat op – indsæt/ret disse rækker i fanen Spots:\n" + "\n".join(sheet_rows))
    else:
        with open(SPOTS_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(spots)
    out = Path(args.mappe) / "synk.json"
    out.write_text(json.dumps(synk, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Synk-felter til databasen: {out}")


if __name__ == "__main__":
    with catalog_lock():
        main()
