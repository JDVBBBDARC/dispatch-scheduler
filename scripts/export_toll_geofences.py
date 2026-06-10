"""Extract all toll plaza coordinates from static/toll_rates.json and
produce a CSV the user can use as a reference while creating geofences
in Cartrack Fleet Web.

Output columns:
    geofence_name   — exactly what to type in Cartrack ("Toll - <Plaza>")
    expressway      — for organizing data entry by route
    latitude        — center point, 6 decimals
    longitude       — center point, 6 decimals
    radius_m        — recommended radius
    google_maps_url — click-to-verify in browser

Run from project root:
    python scripts/export_toll_geofences.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / 'static' / 'toll_rates.json'
OUT  = ROOT / 'toll_geofences_for_cartrack.csv'

# Pretty expressway labels — keeps the CSV easy to scan.
EXPRESSWAY_LABEL = {
    'NLEX_SCTEX':       'NLEX / SCTEX',
    'Skyway_SLEX_MCX':  'Skyway / SLEX / MCX',
    'Skyway_Stage3':    'Skyway Stage 3',
    'CALAX':            'CALAX',
    'CAVITEX':          'CAVITEX',
    'STAR':             'STAR Tollway',
    'TPLEX':            'TPLEX',
    'NAIAX':            'NAIAX',
    'NLEX_Connector':   'NLEX Connector',
    'Harbor_Link':      'Harbor Link',
}

def main():
    with open(SRC, encoding='utf-8') as f:
        data = json.load(f)

    rows = []
    for exp_key, exp_block in data.items():
        coords = exp_block.get('coordinates') or {}
        label  = EXPRESSWAY_LABEL.get(exp_key, exp_key)
        for plaza_name, c in coords.items():
            lat = c.get('lat')
            lng = c.get('lng')
            radius = c.get('radius_m', 200)
            if lat is None or lng is None:
                continue
            rows.append({
                'geofence_name':   f'Toll - {plaza_name}',
                'expressway':      label,
                'latitude':        f'{lat:.6f}',
                'longitude':       f'{lng:.6f}',
                'radius_m':        radius,
                'google_maps_url': f'https://www.google.com/maps?q={lat},{lng}',
            })

    # Sort by expressway, then by name so data entry follows a route.
    rows.sort(key=lambda r: (r['expressway'], r['geofence_name']))

    # utf-8-sig adds a BOM so Excel on Windows shows ñ/é/etc. correctly
    # without forcing the user to manually pick UTF-8 on import.
    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=[
            'geofence_name', 'expressway',
            'latitude', 'longitude', 'radius_m',
            'google_maps_url',
        ])
        w.writeheader()
        w.writerows(rows)

    # Summary counts per expressway
    from collections import Counter
    counts = Counter(r['expressway'] for r in rows)
    print(f'Wrote {len(rows)} plazas to {OUT.name}')
    print()
    print(f'{"Expressway":<25} {"Plazas":>7}')
    print('-' * 35)
    for exp, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f'{exp:<25} {n:>7}')

if __name__ == '__main__':
    main()
