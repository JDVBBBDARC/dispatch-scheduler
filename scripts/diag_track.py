"""Pull a vehicle's raw Cartrack event track for a short PHT time
window and measure how close it passed to given toll booths.

Answers "did the truck actually pass plaza X, or did the geofence
miss it?" — the local DB only records geofences that FIRED, so this
hits the Cartrack API for the raw positions.

IMPORTANT: Cartrack's event timestamps are Asia/Manila (PHT), and the
CartrackEvent.created_at values stored locally are naive UTC (PHT-8).
Pass this script the window in PHT.

Usage on PythonAnywhere:
    python scripts/diag_track.py 31524271 "2026-07-20 22:30" "2026-07-20 23:10"

(31524271 = TH02 / NGU7958. Default booths scanned: Balagtas, Bocaue.)
"""
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app_v3 import app                                          # noqa: E402
from cartrack_client import CartrackClient                     # noqa: E402
from cartrack_poll import _bootstrap_env_from_wsgi, haversine_meters  # noqa: E402

BOOTHS = {'Balagtas': (14.84093, 120.89942),
          'Bocaue':   (14.80209, 120.94244)}


def _pos(e):
    """Best-effort (lat, lng) from an event dict of unknown shape."""
    for latk, lngk in (('latitude', 'longitude'), ('lat', 'lng'),
                       ('lat', 'lon')):
        if e.get(latk) is not None and e.get(lngk) is not None:
            return float(e[latk]), float(e[lngk])
    loc = e.get('location') or e.get('position') or {}
    if isinstance(loc, dict):
        for latk, lngk in (('latitude', 'longitude'), ('lat', 'lng')):
            if loc.get(latk) is not None and loc.get(lngk) is not None:
                return float(loc[latk]), float(loc[lngk])
    return None


def main():
    if len(sys.argv) < 4:
        print('Usage: python scripts/diag_track.py <cartrack_id> '
              '"YYYY-MM-DD HH:MM" "YYYY-MM-DD HH:MM"   (times in PHT)')
        return
    vid = str(sys.argv[1])
    start = datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M')
    end   = datetime.strptime(sys.argv[3], '%Y-%m-%d %H:%M')

    _bootstrap_env_from_wsgi()
    with app.app_context():
        cc = CartrackClient.from_env()
        print(f'Fetching fleet events {start} .. {end} (PHT)…')
        events, err = cc.get_events(start, end)
        if err:
            print('API note:', err)
        events = events or []
        print(f'total fleet events in window: {len(events)}')
        if events:
            print('event keys:', list(events[0].keys()))

        mine = [e for e in events if str(e.get('vehicle_id')) == vid]
        print(f'events for vehicle {vid}: {len(mine)}')
        print()
        print('ts | ' + ' | '.join(f'd_{b}' for b in BOOTHS) + ' | lat,lng | type')
        closest = {b: 9e9 for b in BOOTHS}
        rows = []
        for e in mine:
            p = _pos(e)
            if not p:
                continue
            ds = {b: haversine_meters(p[0], p[1], c[0], c[1])
                  for b, c in BOOTHS.items()}
            for b, d in ds.items():
                closest[b] = min(closest[b], d)
            ts = e.get('event_ts') or e.get('timestamp') or e.get('ts') or '?'
            rows.append((ts, ds, p,
                         e.get('event_type') or e.get('type') or ''))
        for ts, ds, p, typ in sorted(rows, key=lambda r: str(r[0])):
            dstr = ' | '.join(f'{round(ds[b]):>5}' for b in BOOTHS)
            print(f'  {ts} | {dstr} | {p[0]:.5f},{p[1]:.5f} | {typ}')
        print()
        print('Closest approach:',
              ' · '.join(f'{b} {round(d)}m' for b, d in closest.items()))
        print('If Balagtas closest < ~120m but no enter fired -> geofence '
              'missed it (fix Balagtas). If far -> truck did not pass '
              'Balagtas booth (Bocaue entry is correct).')


if __name__ == '__main__':
    main()
