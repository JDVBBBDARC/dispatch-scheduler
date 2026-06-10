"""Build the canonical toll_geofences.json from two sources of truth.

Source 1 — ACCURATE (booth-level): the 59 polygons the user drew by hand
on satellite view in Cartrack Fleet Web. extract_accurate_toll_coords.py
pulled their centroids + bounding radii out of the CartrackGeofence
table on PythonAnywhere. These are positioned on the physical booths —
same precision as the manual home geofences in manual_geofences.json.

Source 2 — APPROXIMATE (plaza-level): toll_geofences_for_cartrack.csv,
the original 108-plaza worksheet derived from public data. Coordinates
are 3-decimal approximations that landed up to ~2km from the actual
booth (the Pulilan marker famously sat on a residential compound).

Merge rules:
  1. Booth entries keep their Cartrack identity verbatim — name, centroid,
     tight radius. Detection runs against THESE in Cartrack, so the JSON
     must mirror them, not re-derive them.
  2. A CSV plaza "covered" by one or more booths is corrected: its row
     gets the centroid of the booth cluster and a radius that wraps the
     cluster. Booths >500m apart are split into separate clusters rather
     than merged (a 2km blob spanning highway between two barriers would
     re-introduce drive-by false positives).
  3. CSV plazas with no booths stay approximate and are flagged
     "accuracy": "approximate" — that flag IS the to-draw checklist.
  4. Known name variants are aliased (Florida->Floridablanca,
     Mabiga->Mabalacat, etc.) so the match doesn't silently miss.

Outputs:
  toll_geofences.json                 (project root — canonical reference)
  toll_geofences_for_cartrack.csv     (rewritten: accurate coords + status col)
  stdout                              (analysis report: coverage, error sizes)

Usage:
  python integration_doc/build_toll_geofences.py
"""
import csv
import json
import math
import os
import re
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# ── Source 1: booth-accurate entries from the user's Cartrack drawings ──
# [name, expressway, lat, lng, radius_m] — as extracted on PythonAnywhere
# from CartrackGeofence.polygon_wkt (centroid + bounding radius + 20m pad).
ACCURATE_BOOTHS = [
    ["Toll - Angeles",            "NLEX / SCTEX",   15.161679, 120.610743,  85],
    ["Toll - Balagtas",           "NLEX / SCTEX",   14.840927, 120.899421,  94],
    ["Toll - Balintawak",         "NLEX / SCTEX",   14.678612, 121.000351,  68],
    ["Toll - Binalonan",          "TPLEX",          16.049817, 120.564537,  73],
    ["Toll - Bocaue",             "NLEX / SCTEX",   14.802092, 120.942443, 227],
    ["Toll - Carmen",             "TPLEX",          15.873864, 120.620198, 108],
    ["Toll - Ciudad De Victoria", "NLEX / SCTEX",   14.791490, 120.950273,  78],
    ["Toll - Concepcion",         "NLEX / SCTEX",   15.316891, 120.628537,  78],
    ["Toll - Dau 1",              "NLEX / SCTEX",   15.178013, 120.605784,  53],
    ["Toll - Dau 2",              "NLEX / SCTEX",   15.179824, 120.602744,  56],
    ["Toll - Dinalupihan",        "NLEX / SCTEX",   14.855140, 120.456088,  78],
    ["Toll - Dolores",            "NLEX / SCTEX",   15.240019, 120.571894,  75],
    ["Toll - España",             "NLEX Connector", 14.618542, 120.990974,  96],
    ["Toll - Florida",            "NLEX / SCTEX",   15.015488, 120.474083,  76],
    ["Toll - Gerona",             "TPLEX",          15.615852, 120.634126,  85],
    ["Toll - Hacienda Luisita 1", "NLEX / SCTEX",   15.433379, 120.665203,  68],
    ["Toll - Hacienda Luisita 2", "NLEX / SCTEX",   15.434205, 120.667922,  73],
    ["Toll - Karuhatan",          "NLEX / SCTEX",   14.693737, 120.976846,  97],
    ["Toll - Lingunan",           "NLEX / SCTEX",   14.722207, 120.984543,  46],
    ["Toll - Mabiga 1",           "NLEX / SCTEX",   15.197366, 120.583428,  52],
    ["Toll - Mabiga 2",           "NLEX / SCTEX",   15.198004, 120.582945,  55],
    ["Toll - Mabiga 3",           "NLEX / SCTEX",   15.197775, 120.580252,  60],
    ["Toll - Mabiga 4",           "NLEX / SCTEX",   15.197437, 120.580227,  59],
    ["Toll - Marilao 1",          "NLEX / SCTEX",   14.772287, 120.956299,  57],
    ["Toll - Marilao 2",          "NLEX / SCTEX",   14.776683, 120.957279,  55],
    ["Toll - Mexico 1",           "NLEX / SCTEX",   15.108303, 120.663081,  60],
    ["Toll - Meycauayan 1",       "NLEX / SCTEX",   14.744778, 120.972471,  70],
    ["Toll - Meycauayan 2",       "NLEX / SCTEX",   14.747672, 120.972344,  47],
    ["Toll - Mindanao Avenue",    "NLEX / SCTEX",   14.693546, 121.017401,  73],
    ["Toll - Moncada",            "TPLEX",          15.718071, 120.616032,  77],
    ["Toll - Paniqui",            "TPLEX",          15.665494, 120.618075,  73],
    ["Toll - Porac",              "NLEX / SCTEX",   15.122911, 120.511440,  73],
    ["Toll - Pozorrubio",         "TPLEX",          16.129713, 120.525549,  98],
    ["Toll - Pulilan 1",          "NLEX / SCTEX",   14.909280, 120.815545,  52],
    ["Toll - Pulilan 2",          "NLEX / SCTEX",   14.909339, 120.817037,  64],
    ["Toll - Pulilan 3",          "NLEX / SCTEX",   14.907246, 120.817047,  50],
    ["Toll - Pulilan 4",          "NLEX / SCTEX",   14.907593, 120.818385,  48],
    ["Toll - Rosario",            "TPLEX",          16.217638, 120.498324, 101],
    ["Toll - San Fernando 1",     "NLEX / SCTEX",   15.048231, 120.695172,  74],
    ["Toll - San Fernando 2",     "NLEX / SCTEX",   15.049788, 120.693880,  64],
    ["Toll - San Fernando 3",     "NLEX / SCTEX",   15.051404, 120.695481,  77],
    ["Toll - San Simon 1",        "NLEX / SCTEX",   14.988886, 120.751030,  63],
    ["Toll - San Simon 2",        "NLEX / SCTEX",   14.988909, 120.750223,  55],
    ["Toll - Sison",              "TPLEX",          16.183321, 120.513868,  85],
    ["Toll - Sta Ines",           "NLEX / SCTEX",   15.221988, 120.587939,  65],
    ["Toll - Sta Rita 1",         "NLEX / SCTEX",   14.863195, 120.859890,  78],
    ["Toll - Sta Rita 2",         "NLEX / SCTEX",   14.861620, 120.857575,  76],
    ["Toll - Tabang 1",           "NLEX / SCTEX",   14.837456, 120.868084,  94],
    ["Toll - Tambubong 1",        "NLEX / SCTEX",   14.814720, 120.937266,  58],
    ["Toll - Tambubong 2",        "NLEX / SCTEX",   14.814540, 120.933915,  55],
    ["Toll - Tarlac",             "NLEX / SCTEX",   15.462897, 120.675779,  87],
    ["Toll - Tarlac 2",           "NLEX / SCTEX",   15.512896, 120.665790,  85],
    ["Toll - Tipo/SFEX 1",        "NLEX / SCTEX",   14.842278, 120.354357,  72],
    ["Toll - Tipo/SFEX 2",        "NLEX / SCTEX",   14.841799, 120.353912,  68],
    ["Toll - Urdaneta",           "TPLEX",          16.002084, 120.579823, 114],
    ["Toll - Valenzuela 1",       "NLEX / SCTEX",   14.709338, 120.992669,  53],
    ["Toll - Valenzuela 2",       "NLEX / SCTEX",   14.707545, 120.992961,  58],
    ["Toll - Valenzuela 3",       "NLEX / SCTEX",   14.727983, 120.982495,  35],
    ["Toll - Victoria",           "TPLEX",          15.542651, 120.642775,  71],
]

# Cartrack-drawing names that don't literally match the CSV plaza name.
# Keys/values are normalised (see _norm_plaza).
NAME_ALIASES = {
    "florida":  "floridablanca",   # NLEX exit named after the town
    "mabiga":   "mabalacat",       # Mabalacat plaza sits in Brgy. Mabiga
}

# Booths farther apart than this are NOT merged into one plaza circle.
# Merging e.g. Valenzuela 1/2 (main barrier) with Valenzuela 3 (2.1km
# north) would create a blob covering plain highway — false positives.
CLUSTER_SPLIT_M = 500


def _norm_plaza(name):
    """Normalise a plaza/booth name to its match key.

    'Toll - Sta. Ines'   -> 'sta ines'
    'Toll - Pulilan 3'   -> 'pulilan'      (booth number stripped)
    'Toll - Florida'     -> 'floridablanca' (alias applied)
    """
    s = name.strip()
    s = re.sub(r'^Toll\s*-\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+\d+$', '', s)          # strip trailing booth number
    s = s.lower().replace('.', '').strip()
    s = re.sub(r'\s+', ' ', s)
    return NAME_ALIASES.get(s, s)


def _haversine_m(lat1, lng1, lat2, lng2):
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _cluster_booths(booths):
    """Split a plaza's booths into clusters of mutually-near booths.

    Greedy single-link: a booth joins a cluster if it's within
    CLUSTER_SPLIT_M of ANY member. Booth counts per plaza are tiny
    (max 4) so O(n^2) is fine.
    """
    clusters = []
    for b in booths:
        placed = False
        for cl in clusters:
            if any(_haversine_m(b[2], b[3], m[2], m[3]) <= CLUSTER_SPLIT_M
                   for m in cl):
                cl.append(b)
                placed = True
                break
        if not placed:
            clusters.append([b])
    return clusters


def _cluster_centroid_radius(cluster):
    """Centroid of booth centroids + radius wrapping every booth circle."""
    lat = sum(b[2] for b in cluster) / len(cluster)
    lng = sum(b[3] for b in cluster) / len(cluster)
    radius = max(_haversine_m(lat, lng, b[2], b[3]) + b[4] for b in cluster)
    return round(lat, 6), round(lng, 6), int(math.ceil(radius))


def main():
    # ── Load the CSV worksheet ────────────────────────────────────────
    # utf-8-sig: the worksheet was exported with a BOM for Excel; plain
    # utf-8 leaves ﻿ glued to the first header name.
    csv_path = os.path.join(_ROOT, 'toll_geofences_for_cartrack.csv')
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        csv_rows = list(csv.DictReader(f))

    # Group booths by (match_key, expressway) — expressway disambiguates
    # e.g. Balintawak (NLEX) from Balintawak (Skyway Stage 3).
    booths_by_plaza = defaultdict(list)
    for b in ACCURATE_BOOTHS:
        booths_by_plaza[(_norm_plaza(b[0]), b[1])].append(b)

    # ── Pass 1: correct CSV rows that now have booth data ─────────────
    out_csv_rows = []
    matched_keys = set()
    corrections = []   # (plaza, old_err_m) for the report

    for row in csv_rows:
        key = (_norm_plaza(row['geofence_name']), row['expressway'])
        booths = booths_by_plaza.get(key)
        if not booths:
            row['status'] = 'TO_DRAW'
            out_csv_rows.append(row)
            continue

        matched_keys.add(key)
        clusters = _cluster_booths(booths)
        # Primary cluster = the largest (the main barrier). Secondary
        # clusters become their own rows named after their first booth.
        clusters.sort(key=len, reverse=True)
        primary, extras = clusters[0], clusters[1:]

        old_lat, old_lng = float(row['latitude']), float(row['longitude'])
        lat, lng, radius = _cluster_centroid_radius(primary)
        corrections.append((row['geofence_name'],
                            _haversine_m(old_lat, old_lng, lat, lng)))

        row['latitude'], row['longitude'] = f'{lat:.6f}', f'{lng:.6f}'
        row['radius_m'] = str(radius)
        row['google_maps_url'] = f'https://www.google.com/maps?q={lat},{lng}'
        row['status'] = 'DRAWN'
        out_csv_rows.append(row)

        for cl in extras:
            lat2, lng2, radius2 = _cluster_centroid_radius(cl)
            out_csv_rows.append({
                'geofence_name': cl[0][0],
                'expressway': row['expressway'],
                'latitude': f'{lat2:.6f}', 'longitude': f'{lng2:.6f}',
                'radius_m': str(radius2),
                'google_maps_url': f'https://www.google.com/maps?q={lat2},{lng2}',
                'status': 'DRAWN',
            })

    # ── Pass 2: Cartrack drawings with NO CSV plaza (e.g. Lingunan) ───
    new_from_cartrack = []
    for key, booths in booths_by_plaza.items():
        if key in matched_keys:
            continue
        for cl in _cluster_booths(booths):
            lat, lng, radius = _cluster_centroid_radius(cl)
            display = re.sub(r'\s+\d+$', '', cl[0][0])
            new_from_cartrack.append(display)
            out_csv_rows.append({
                'geofence_name': display,
                'expressway': key[1],
                'latitude': f'{lat:.6f}', 'longitude': f'{lng:.6f}',
                'radius_m': str(radius),
                'google_maps_url': f'https://www.google.com/maps?q={lat},{lng}',
                'status': 'DRAWN',
            })

    # ── Write the corrected CSV (stable order: expressway, name) ──────
    out_csv_rows.sort(key=lambda r: (r['expressway'], r['geofence_name']))
    fieldnames = ['geofence_name', 'expressway', 'latitude', 'longitude',
                  'radius_m', 'google_maps_url', 'status']
    # Write back with BOM so Excel keeps opening it cleanly (ñ etc.).
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(out_csv_rows)

    # ── Build toll_geofences.json — canonical reference ───────────────
    # Booth-level where drawn (mirrors Cartrack exactly), plaza-level
    # approximate elsewhere (the to-draw checklist).
    entries = []
    for b in ACCURATE_BOOTHS:
        entries.append({
            'name':       b[0],
            'plaza':      re.sub(r'\s+\d+$', '',
                                 re.sub(r'^Toll\s*-\s*', '', b[0])),
            'expressway': b[1],
            'category':   'toll',
            'lat':        b[2],
            'lng':        b[3],
            'radius_m':   b[4],
            'accuracy':   'booth',
        })
    for row in out_csv_rows:
        if row['status'] != 'TO_DRAW':
            continue
        entries.append({
            'name':       row['geofence_name'],
            'plaza':      re.sub(r'^Toll\s*-\s*', '', row['geofence_name']),
            'expressway': row['expressway'],
            'category':   'toll',
            'lat':        float(row['latitude']),
            'lng':        float(row['longitude']),
            'radius_m':   int(row['radius_m']),
            'accuracy':   'approximate',
        })

    entries.sort(key=lambda e: (e['expressway'], e['name']))
    doc = {
        '_comment': (
            'Canonical toll geofence reference. accuracy="booth" entries '
            'mirror the polygons drawn by hand in Cartrack Fleet Web '
            '(centroid + bounding radius) — booth-precise, same method as '
            'manual_geofences.json. accuracy="approximate" entries come '
            'from public data (up to ~2km off) and are the checklist of '
            'plazas still to be drawn in Cartrack. Regenerate with: '
            'python integration_doc/build_toll_geofences.py'
        ),
        'booth_accurate': sum(1 for e in entries if e['accuracy'] == 'booth'),
        'approximate':    sum(1 for e in entries if e['accuracy'] == 'approximate'),
        'plazas': entries,
    }
    json_path = os.path.join(_ROOT, 'toll_geofences.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    # ── Report ─────────────────────────────────────────────────────────
    print(f'CSV plazas total:            {len(csv_rows)}')
    print(f'  corrected from Cartrack:   {len(corrections)}')
    print(f'  still approximate:         '
          f'{sum(1 for r in out_csv_rows if r["status"] == "TO_DRAW")}')
    print(f'  new rows (Cartrack-only):  {new_from_cartrack}')
    print()
    print('Largest coordinate errors fixed (old CSV vs booth-accurate):')
    for name, err in sorted(corrections, key=lambda c: -c[1])[:15]:
        print(f'  {name:32s} {err:7.0f} m off')
    avg = sum(e for _, e in corrections) / len(corrections)
    print(f'\n  average error of the old coords: {avg:.0f} m')
    print()
    print(f'Wrote {json_path}')
    print(f'Rewrote {csv_path}')


if __name__ == '__main__':
    main()
