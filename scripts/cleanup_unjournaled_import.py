"""One-off cleanup for an Excel schedule import that predates the
revert feature.

The first workbook import ran before batches were journaled to
instance/schedule_import_batches.json, so the in-app "Revert this
import" button has nothing to point at. This script finds the trips
that import created and removes them, so the workbook can be
re-imported cleanly with the current rules (trip types, per-trip
volume, 4 sheets, hauling-to-Others).

How import-created trips are identified:
  - the Wave date falls in the given range (default: May 2026, the
    month of the workbook), AND
  - TripRecord.updated_by IS NULL — the importer never stamps it,
    while every manual save through the Schedule UI does.

SAFETY GUARD: the Google-Sheets RESTORE feature also creates trips
without updated_by. If this database has ever run "Restore from
Google Sheets", the NULL heuristic cannot distinguish restored manual
trips from imported ones — the script detects that from the change
log and refuses to run (override with --force-even-if-restored only
if you are certain the range contains no restored data).

An imported trip that a dispatcher has since EDITED carries their
updated_by and is deliberately left alone. Master data auto-created
by the old import is NOT touched — the re-import reuses it by name.

NOTE: the OLD importer dated rows whose date cell held text (e.g.
'Cancelled') as the day the import RAN, not a May date. After the
main run, the script scans for updated_by-NULL trips OUTSIDE the
range and prints them — re-run with --from/--to over that day to
sweep the residue, e.g.:

    python scripts/cleanup_unjournaled_import.py --from 2026-07-01 --to 2026-07-04 --apply

Run on PythonAnywhere:

    python scripts/cleanup_unjournaled_import.py             # dry-run
    python scripts/cleanup_unjournaled_import.py --apply     # delete
"""
import os
import sys
from collections import Counter
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app_v3 import (app, log_change, _load_import_batches,   # noqa: E402
                    _save_import_batches)
from models_v2 import db, Wave, TripRecord, ChangeLog        # noqa: E402


def _arg(flag, default):
    if flag in sys.argv:
        return sys.argv[sys.argv.index(flag) + 1]
    return default


def main():
    apply = '--apply' in sys.argv
    d_from = date.fromisoformat(_arg('--from', '2026-05-01'))
    d_to   = date.fromisoformat(_arg('--to',   '2026-05-31'))

    with app.app_context():
        # ── Guard: has this DB ever been restored from Google Sheets? ─
        # The restore path also leaves updated_by NULL, which would make
        # restored MANUAL trips indistinguishable from imported ones.
        restored = (ChangeLog.query
                    .filter(ChangeLog.action.like('Restored data%'))
                    .first())
        if restored and '--force-even-if-restored' not in sys.argv:
            print('ABORTING: this database has a "Restore from Google '
                  'Sheets" event in its change log:')
            print(f'  [{restored.timestamp}] {restored.action}')
            print('Restored trips also lack updated_by, so this cleanup '
                  'could delete manually-encoded trips that came back '
                  'through that restore. If you are certain the date '
                  'range holds no restored data, re-run with '
                  '--force-even-if-restored.')
            sys.exit(1)

        trips = (TripRecord.query.join(Wave)
                 .filter(Wave.date >= d_from, Wave.date <= d_to,
                         TripRecord.updated_by.is_(None))
                 .all())
        kept_manual = (TripRecord.query.join(Wave)
                       .filter(Wave.date >= d_from, Wave.date <= d_to,
                               TripRecord.updated_by.isnot(None))
                       .count())

        per_date = Counter(t.wave.date.isoformat() for t in trips)
        print(f'Range {d_from} .. {d_to}')
        print(f'Import-created trips found (updated_by is NULL): {len(trips)}')
        print(f'Manually saved/edited trips in range (KEPT):      {kept_manual}')
        print()
        for dstr in sorted(per_date):
            print(f'  {dstr}: {per_date[dstr]} trips')
        print()
        print('Sample (first 5):')
        for t in trips[:5]:
            print(f'  {t.wave.date} wave#{t.wave.wave_number} trip#{t.trip_number} '
                  f'plate={t.plate.display if t.plate else "-"} '
                  f'client={t.client.name if t.client else "-"} '
                  f'dr={t.dr_no or "-"} status={t.status}')

        # ── Residue radar: NULL-updated_by trips OUTSIDE the range ────
        # (the old importer stamped garbage-dated rows with the day the
        # import ran — usually not a workbook date).
        outside = (db.session.query(Wave.date,
                                    db.func.count(TripRecord.id))
                   .join(TripRecord, TripRecord.wave_id == Wave.id)
                   .filter(TripRecord.updated_by.is_(None),
                           db.or_(Wave.date < d_from, Wave.date > d_to))
                   .group_by(Wave.date).all())
        if outside:
            print()
            print('NOTE — possible import residue OUTSIDE this range '
                  '(updated_by-NULL trips). Re-run with --from/--to over '
                  'these dates if they are not legitimate data:')
            for dd, n in sorted(outside):
                print(f'  {dd}: {n} trips')

        if not trips:
            print('Nothing to clean up in range.')
            return
        if not apply:
            print()
            print('DRY-RUN only — re-run with --apply to delete the '
                  f'{len(trips)} trips above (and their waves if left '
                  'empty).')
            return

        # ── Delete (chunked — PA SQLite caps bound params at 999) ─────
        ids = [t.id for t in trips]
        affected_waves = {t.wave_id for t in trips}
        removed = 0
        for i in range(0, len(ids), 500):
            removed += (TripRecord.query
                        .filter(TripRecord.id.in_(ids[i:i + 500]))
                        .delete(synchronize_session=False))
        db.session.flush()

        # Only waves the deleted trips lived in — a pre-created empty
        # wave elsewhere in the range is not ours to remove.
        empty_waves = 0
        for wid in affected_waves:
            w = db.session.get(Wave, wid)
            if w is not None and not TripRecord.query.filter_by(
                    wave_id=wid).first():
                db.session.delete(w)
                empty_waves += 1

        db.session.commit()

        # ── Retire journaled batches that referenced deleted trips ────
        # SQLite reuses freed rowids, so a stale non-reverted batch
        # could later "revert" freshly re-imported trips by id.
        deleted_set = set(ids)
        batches = _load_import_batches()
        retired = 0
        for b in batches:
            if not b.get('reverted') and deleted_set.intersection(
                    b.get('trips', [])):
                b['reverted'] = True
                b['reverted_note'] = 'superseded by cleanup script'
                retired += 1
        if retired:
            _save_import_batches(batches)

        # log_change reads the Flask session for the user name, which
        # doesn't exist in a console run — never let logging failure
        # mask a successful cleanup.
        try:
            with app.test_request_context():
                log_change(
                    f'Cleanup of unjournaled Excel import: removed '
                    f'{removed} trips and {empty_waves} empty waves '
                    f'({d_from}..{d_to})', 'trip')
                db.session.commit()
        except Exception as e:
            print(f'(change-log entry skipped: {e})')

        print()
        print(f'DELETED {removed} trips and {empty_waves} now-empty waves.'
              + (f' Retired {retired} stale journal batch(es).'
                 if retired else ''))
        print('You can now re-upload the workbook (Schedule -> Import '
              'Excel) to import it with the current rules.')


if __name__ == '__main__':
    main()
