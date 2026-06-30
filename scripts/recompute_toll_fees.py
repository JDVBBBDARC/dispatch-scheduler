"""Back-fill GPS toll fees for trip_closed events that have no fee yet.

After the June 2026 plaza-resolution fix (commit 986cb41), plaza names
like "Florida" now resolve to the fee-matrix key "Floridablanca" and
compute a fee. Events DETECTED before that fix stored a null toll_fee
("—" in the Toll Log). This script re-resolves their stored entry/exit
names through the improved resolver and back-fills the fee wherever it
is now computable — without touching anything that already has a fee.

Some old rows can't be recovered from stored data alone: a geofence
like "Toll - Clark North" had its direction word stripped BEFORE the
plaza name was stored, so the row only kept a bare "Clark" (which maps
to neither "Clark North" nor "Clark South"). Those are reported, not
guessed — the worker captures them correctly going forward.

Run on PythonAnywhere, where the production DB lives:

    python scripts/recompute_toll_fees.py            # dry-run (no writes)
    python scripts/recompute_toll_fees.py --apply     # save the back-fill

Idempotent: a row that gets a fee no longer matches the filter on a
re-run, so running it twice is safe.
"""
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app_v3 import app                                      # noqa: E402
from models_v2 import db, CartrackEvent, Plate              # noqa: E402
from cartrack_poll import compute_toll_fee, _resolve_plaza  # noqa: E402


def main():
    apply = '--apply' in sys.argv

    with app.app_context():
        rows = (CartrackEvent.query
                .filter(CartrackEvent.event_type == 'trip_closed',
                        CartrackEvent.toll_fee.is_(None),
                        CartrackEvent.toll_entry.isnot(None),
                        CartrackEvent.toll_exit.isnot(None))
                .all())

        fixed = 0
        unresolved = []          # (entry, exit) pairs we still can't price

        for ev in rows:
            # Re-resolve each stored name to its canonical fee-matrix key.
            # Handles e.g. "Florida" -> "Floridablanca" via the new alias;
            # an already-canonical name resolves to itself.
            ce, _ = _resolve_plaza(ev.toll_entry or '')
            cx, _ = _resolve_plaza(ev.toll_exit or '')
            entry  = ce or ev.toll_entry
            exit_  = cx or ev.toll_exit

            toll_class = 'Class 3'
            if ev.plate_id:
                p = db.session.get(Plate, ev.plate_id)
                if p and p.toll_class:
                    toll_class = p.toll_class

            fee, exp = compute_toll_fee(entry, exit_, toll_class)
            if fee is not None:
                fixed += 1
                print(f'  FIX  {ev.toll_entry!r}->{ev.toll_exit!r}'
                      f'  =>  {entry!r}->{exit_!r}  PHP {fee} ({exp})')
                if apply:
                    ev.toll_fee   = fee
                    ev.expressway = exp
                    ev.toll_entry = entry
                    ev.toll_exit  = exit_
                    ev.notes      = 'gps-detected (recomputed)'
            else:
                unresolved.append((ev.toll_entry, ev.toll_exit))

        if apply:
            db.session.commit()

        print()
        print(f'trip_closed rows with no fee: {len(rows)}')
        print(f'  recomputed a fee:   {fixed}'
              + ('' if apply else '   (DRY-RUN — re-run with --apply to save)'))
        print(f'  still unresolvable: {len(unresolved)}')

        if unresolved:
            names = Counter()
            for a, b in unresolved:
                names[a] += 1
                names[b] += 1
            print('  unresolvable plaza names (worker handles these going '
                  'forward; listed so you can spot any bad geofence name):')
            for name, n in names.most_common():
                print(f'    {name!r}: {n}')


if __name__ == '__main__':
    main()
