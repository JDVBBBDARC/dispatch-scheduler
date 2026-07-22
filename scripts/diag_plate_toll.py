"""Quick diagnostic: show a plate's toll-geofence history from the
local DB (fast, no Cartrack API call).

Usage on PythonAnywhere:
    python scripts/diag_plate_toll.py            # defaults to TH02, 5 days
    python scripts/diag_plate_toll.py TH02
    python scripts/diag_plate_toll.py DT30 7     # DT30, last 7 days

Lists every plate whose body_no matches the search term (so you can
confirm which physical unit it is), then prints that unit's toll
enter/exit/trip_closed events with coordinates — so we can see which
plaza fired, which was missed, and how trips paired.
"""
import os
import sys
from datetime import timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app_v3 import app                                     # noqa: E402
from models_v2 import db, Plate, CartrackEvent, utc_now   # noqa: E402


def main():
    term = sys.argv[1] if len(sys.argv) > 1 else 'TH02'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    like = f'%{term.replace("-", "").replace(" ", "")}%'

    with app.app_context():
        # Match on body_no ignoring spaces/dashes (TH02 == TH-02 == TH 02)
        cands = [p for p in Plate.query.all()
                 if term.replace('-', '').replace(' ', '').upper()
                 in ((p.body_no or '').replace('-', '').replace(' ', '').upper())]
        print(f'=== Plates matching {term!r} ===')
        for p in cands:
            print(f'  {p.display} | body={p.body_no} | plate={p.plate_no} '
                  f'| active={p.active} | cartrack_id={p.cartrack_vehicle_id}')
        if not cands:
            print('  (none)')
            return

        target = cands[0]
        print()
        print(f'=== {target.display} toll events (last {days} days) ===')
        since = utc_now() - timedelta(days=days)
        rows = (CartrackEvent.query
                .filter(CartrackEvent.plate_id == target.id,
                        CartrackEvent.created_at >= since)
                .order_by(CartrackEvent.created_at).all())
        for e in rows:
            what = e.plaza_name or f'{e.toll_entry} -> {e.toll_exit}'
            coord = (f'{e.lat:.5f},{e.lng:.5f}'
                     if e.lat is not None and e.lng is not None else '—')
            print(f'  {e.created_at} | {e.event_type:11s} | {what:32s} | {coord}')
        if not rows:
            print('  (no toll events in this window)')


if __name__ == '__main__':
    main()
