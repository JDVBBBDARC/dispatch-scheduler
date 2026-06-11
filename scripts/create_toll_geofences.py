"""Activate the not-yet-drawn toll plazas by creating their geofences
in Cartrack via the Fleet API.

The 41 plazas with accuracy="osm" in toll_geofences.json have
booth-accurate positions (surveyed by OpenStreetMap mappers from
satellite imagery) but NO Cartrack geofence yet — so the polling
worker can't detect transits through them. This script creates a
circular-polygon geofence in Cartrack for each, named with the same
"Toll - X" convention as the hand-drawn ones, which makes them live
for detection on the next geofence sync.

The 28 accuracy="approximate" plazas are skipped on purpose — their
coordinates are unverified (km-level error) and activating them would
create false-positive geofences. Verify those on the map first.

⚠ Cartrack's docs don't publicly confirm the POST payload shape for
/rest/geofences, so run the modes in this order ON PYTHONANYWHERE
(credentials live there):

  python scripts/create_toll_geofences.py              # dry-run list
  python scripts/create_toll_geofences.py --inspect    # show one raw
        geofence JSON from the API -> reveals the real field names
  python scripts/create_toll_geofences.py --create-one # create ONE
        plaza, verify it appears in Cartrack Fleet Web + the API
  python scripts/create_toll_geofences.py --create-all # the rest

If --create-one fails, paste the printed status + body back to the
assistant — the payload will be adapted to the real schema. If the
API turns out to be read-only for geofences (405/403), the fallback
is drawing them manually in Fleet Web using the map labels; the
half-filled markers show exactly where each booth is.

After a successful --create-all:
  1. /truck-cycle-time -> Sync Geofences (pulls them into the app)
  2. python integration_doc/extract_accurate_toll_coords.py
  3. paste the new entries into ACCURATE_BOOTHS in
     integration_doc/build_toll_geofences.py and re-run it
     -> CSV/JSON/map flip those plazas to solid "active" markers.
"""
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cartrack_client import CartrackClient   # noqa: E402

PACING_SECONDS = 2.0   # between creates — the 429 lesson, applied


def _circle_wkt(lat, lng, radius_m, points=16):
    """Circular polygon WKT around (lat, lng). WKT order is lng lat."""
    coords = []
    lat_deg = radius_m / 111_320.0
    lng_deg = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    for i in range(points + 1):           # +1 closes the ring
        ang = 2 * math.pi * i / points
        coords.append(f'{lng + lng_deg * math.sin(ang):.6f} '
                      f'{lat + lat_deg * math.cos(ang):.6f}')
    return f'POLYGON(({", ".join(coords)}))'


def _load_targets():
    with open(os.path.join(_ROOT, 'toll_geofences.json'), encoding='utf-8') as f:
        doc = json.load(f)
    return [p for p in doc['plazas'] if p['accuracy'] == 'osm']


def _existing_names(cc):
    fences, err = cc.list_geofences()
    if err:
        print(f'WARNING: could not list existing geofences: {err}')
        return set()
    return {(g.get('name') or '').strip().upper() for g in fences}


def _create(cc, plaza):
    """Attempt to create one geofence. Returns (ok, status, body)."""
    payload = {
        'name':        plaza['name'],
        'description': f"{plaza['expressway']} toll plaza "
                       f"(auto-created from OSM booth position)",
        'polygon_wkt': _circle_wkt(plaza['lat'], plaza['lng'],
                                   plaza['radius_m']),
    }
    status, body = cc._call('/rest/geofences', method='POST', json=payload)
    ok = status in (200, 201)
    return ok, status, body


def main():
    cc = CartrackClient()
    if not cc.configured:
        print('CARTRACK_USERNAME / CARTRACK_PASSWORD not set — run this '
              'on PythonAnywhere where the .env lives.')
        sys.exit(1)

    targets = _load_targets()
    print(f'{len(targets)} OSM-refined plazas eligible for activation.\n')

    if '--inspect' in sys.argv:
        fences, err = cc.list_geofences()
        if err:
            print(f'list_geofences failed: {err}'); sys.exit(1)
        toll = next((g for g in fences
                     if 'TOLL' in (g.get('name') or '').upper()), fences[0])
        print('Raw geofence JSON from the API (use these field names '
              'for the create payload):')
        print(json.dumps(toll, indent=2, default=str))
        return

    create_one = '--create-one' in sys.argv
    create_all = '--create-all' in sys.argv

    existing = _existing_names(cc) if (create_one or create_all) else set()
    created = skipped = failed = 0

    for plaza in targets:
        if not (create_one or create_all):
            print(f"  would create: {plaza['name']:32s} "
                  f"{plaza['expressway']:22s} "
                  f"{plaza['lat']:.6f},{plaza['lng']:.6f} r={plaza['radius_m']}m")
            continue

        if plaza['name'].strip().upper() in existing:
            print(f"  SKIP (already in Cartrack): {plaza['name']}")
            skipped += 1
            continue

        ok, status, body = _create(cc, plaza)
        if ok:
            created += 1
            print(f"  CREATED: {plaza['name']}")
        else:
            failed += 1
            print(f"  FAILED ({status}): {plaza['name']}")
            print(f'    response: {json.dumps(body, default=str)[:400]}')
            if failed == 1 and create_all:
                print('    stopping --create-all after first failure — '
                      'fix the payload first (paste the response above '
                      'back to the assistant).')
                break

        if create_one:
            print('\n--create-one done. Verify in Cartrack Fleet Web, '
                  'then run with --create-all.')
            break
        time.sleep(PACING_SECONDS)

    if create_one or create_all:
        print(f'\ncreated={created} skipped={skipped} failed={failed}')
        if created:
            print('\nNext: Sync Geofences in the app, then re-run the '
                  'extract + build pipeline to flip the map markers '
                  'to solid/active.')
    else:
        print('\nDry-run only. Use --inspect first, then --create-one, '
              'then --create-all.')


if __name__ == '__main__':
    main()
