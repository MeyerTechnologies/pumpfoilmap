#!/usr/bin/env python3
"""Kobler officielle badevandsdata på kartoteket.

    python3 tools/kandidater/vand.py            # bruger data/badevand/eea-dk.json
    python3 tools/kandidater/vand.py --hent     # henter nyeste data fra EEA først

Kilde: EEA's badevandskort (EU's badevandsdirektiv), som indeholder alle ca. 1.040 danske badesteder
(kyst og sø), som kommunerne måler på, med klassifikation for de seneste sæsoner.

For hvert sted i kartoteket findes det nærmeste officielle badested. Ligger det inden for 500 m, skrives
navn, klassifikation og afstand i kolonnen 'badevand', og 'vand' sættes automatisk:
  ok      udmærket eller god badevandskvalitet
  tvivl   tilfredsstillende, ikke klassificeret eller skiftende kvalitet
  nej     ringe kvalitet (EU fraråder badning)
Derefter gælder data/badevand/kendte-forhold*.csv (én fil pr. landsdel er fint): områder med kendte forhold, fx permanent badeforbud,
alger eller vildtreservat, fundet ved opslag. En regel kan kun gøre vurderingen strengere (ok → tvivl → nej),
og dens note skrives i 'badevand'. En regel uden 'vand' tilføjer kun noten. Havne får automatisk "tvivl",
fordi badning i havnebassiner som regel kræver havnens tilladelse.
Uden officielt badested i nærheden sættes 'vand' til 'ukendt'. Så skal badeforhold og regler slås op
manuelt (kommunens side, skilte, havnens ordensreglement …), og resultatet skrives med review.py
(felterne 'vand' og 'vand_note'). En manuel vurdering overskrives aldrig af dette script.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kartotek import catalog_lock, ROOT, distance_m, log, parse_coords, read_catalog, read_csv, today, write_catalog  # noqa: E402

DATA = ROOT / "data/badevand/eea-dk.json"
RULES = ROOT / "data/badevand"  # kendte-forhold*.csv: områder med kendte forhold (badeforbud, alger, reservater)
YEAR = 2025
SERVICE = f"https://water.discomap.eea.europa.eu/arcgis/rest/services/BathingWater/BathingWater_Dyna_WM_{YEAR}/MapServer/3/query"
NEAR_M = 500
DANISH = {"Excellent": "udmærket", "Good": "god", "Sufficient": "tilfredsstillende", "Poor": "ringe",
          "Not classified": "ikke klassificeret"}


def fetch():
    fields = "bathingWaterName,bwWaterCategory,longitude,latitude,qualityStatus,qualityStatus_minus1," \
             "qualityStatus_minus2,bathingWaterIdentifier,bwProfileLink"
    subprocess.run(["curl", "-s", "--max-time", "180", "-G", SERVICE,
                    "--data-urlencode", "where=countryCode='DK'", "--data-urlencode", f"outFields={fields}",
                    "--data-urlencode", "returnGeometry=false", "--data-urlencode", "resultRecordCount=2000",
                    "--data-urlencode", "f=json", "-o", str(DATA)], check=True)


SEVERITY = {"": 0, "ukendt": 0, "ok": 1, "tvivl": 2, "nej": 3}
HARBOUR_NOTE = "Havn: badning i havnebassinet kræver som regel havnens tilladelse (tjek ordensreglementet)."


def load_rules():
    rules = []
    for r in (r for f in sorted(RULES.glob("kendte-forhold*.csv")) for r in read_csv(f)):
        s_, w, n, e = map(float, r["område"].split(","))
        rules.append({**r, "bbox": (s_, w, n, e)})
    return rules


def auto_verdict(site):
    now, *before = site["klasser"]
    if now == "Poor":
        return "nej"
    if now in ("Excellent", "Good") and "Poor" not in before:
        return "ok"
    return "tvivl"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hent", action="store_true")
    args = parser.parse_args()
    DATA.parent.mkdir(parents=True, exist_ok=True)
    if args.hent or not DATA.exists():
        fetch()

    sites = []
    for f in json.loads(DATA.read_text(encoding="utf-8"))["features"]:
        a = f["attributes"]
        sites.append({
            "navn": (a["bathingWaterName"] or "").title(),
            "type": "sø" if a["bwWaterCategory"] == "Lake" else "kyst",
            "pos": (a["latitude"], a["longitude"]),
            "klasser": [a["qualityStatus"], a.get("qualityStatus_minus1"), a.get("qualityStatus_minus2")],
            "profil": a.get("bwProfileLink") or "",
        })

    rules = load_rules()
    catalog = read_catalog()
    changed = 0
    for row in catalog:
        pos = parse_coords(row["koordinater"]) or parse_coords(row["auto_koordinater"])
        if not pos:
            continue
        best = min(sites, key=lambda s: distance_m(pos, s["pos"]))
        d = distance_m(pos, best["pos"])
        if d <= NEAR_M:
            klasser = [DANISH.get(k, k) for k in best["klasser"] if k]
            badevand = (f"{best['navn']} ({best['type']}, {d:.0f} m): {YEAR} {klasser[0]}"
                        + (f", før {' / '.join(klasser[1:])}" if len(klasser) > 1 else ""))
            if best["profil"]:
                badevand += f" · badevandsprofil: {best['profil']}"
            verdict = auto_verdict(best)
        else:
            badevand, verdict = f"Intet officielt badested inden for {NEAR_M} m (nærmeste {d / 1000:.1f} km)", "ukendt"
        notes = []
        for rule in rules:
            s_, w, n, e = rule["bbox"]
            if s_ <= pos[0] <= n and w <= pos[1] <= e:
                notes.append(f"{rule['navn']}: {rule['note']}" + (f" ({rule['kilde']})" if rule["kilde"] else ""))
                if SEVERITY[rule["vand"]] > SEVERITY[verdict]:
                    verdict = rule["vand"]
        cats = row["kategorier"].split()
        if "havn" in cats and not {"badested", "havnebad", "badebro"} & set(cats):
            notes.append(HARBOUR_NOTE)
            if SEVERITY[verdict] < SEVERITY["tvivl"]:
                verdict = "tvivl"
        if notes:
            badevand += " · " + " · ".join(notes)
        if row["badevand"] != badevand:
            row["badevand"] = badevand
            changed += 1
        # Automatisk vurdering kun hvis ingen har vurderet vandet manuelt.
        if not row["vand_note"] and row["vand"] != verdict:
            log("sat vand", row["id"], row["vand"], verdict, "automatisk fra EEA-badevandsdata")
            row["vand"] = verdict
            row["vand_tjekket"] = today()

    write_catalog(catalog)
    reviewed = [r for r in catalog if r["vurdering"] in ("lovende", "måske")]
    counts = {}
    for r in reviewed:
        counts[r["vand"]] = counts.get(r["vand"], 0) + 1
    print(f"{len(sites)} officielle badesteder · {changed} rækker opdateret")
    print("Lovende/måske efter vand: " + ", ".join(f"{k or '–'} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    with catalog_lock():
        main()
