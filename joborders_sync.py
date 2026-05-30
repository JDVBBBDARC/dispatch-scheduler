"""ERP Repair Request → BreakdownLog sync worker.

Pulls repair-request records from the gainersand.ph ERP and upserts them
into the local BreakdownLog table. Runs as a scheduled task on
PythonAnywhere (every 10 min by default), but can also be invoked
manually from a Flask route or from `python joborders_sync.py`.

Design mirrors cartrack_poll.py — same env bootstrap, same Flask app
context pattern, same logger style — so the two integrations look and
feel identical to maintainers.

──────────────────────────────────────────────────────────────────────
Why upsert (not insert-only)?

The ERP record's status changes over its lifecycle (pending → approved →
job-orders complete → released). We want each ERP record to map to ONE
local BreakdownLog row that updates as the ERP state changes. The
jo_external_id column on BreakdownLog is the upsert key.

──────────────────────────────────────────────────────────────────────
Status mapping rules (derived from IT clarification, May 29 2026):

   "May sariling status si maintenance request vs job order; bali isa
    sa basehan para masabi na tapos na yung maintenance request is pag
    complete na lahat ng job order na nilagay sa kanya."

So:
   approver_status != 'APPROVED'              → 'Pending Approval'
   maintenance_approver_status != 'APPROVED'  → 'Pending Approval'
   job_orders all complete                    → 'Fixed'
   otherwise                                  → 'Under Repair'

The local status column accepts {'Under Repair', 'Fixed', 'Standby'}
(see BREAKDOWN_STATUSES in models_v2). 'Pending Approval' is mapped
back to 'Under Repair' for now — we can add a 4th status later if
dispatchers need it as a separate state in the UI.
"""
import logging
import os
import sys
from datetime import datetime, timedelta

# Make this script importable both standalone and from within Flask.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from models_v2 import utc_now


# ─────────────────────────────────────────────────────────────────────
# Env bootstrap — share with cartrack_poll's loader to avoid duplication
# ─────────────────────────────────────────────────────────────────────

def _bootstrap_env():
    """Populate os.environ from the project-root .env (and the PA WSGI
    config as a secondary source). Re-uses cartrack_poll's loader so
    both integrations honour the same precedence rules."""
    try:
        from cartrack_poll import _bootstrap_env_from_wsgi
        _bootstrap_env_from_wsgi()
    except Exception:
        pass  # not fatal — caller may have populated env already


_bootstrap_env()


# ─────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────
_log = logging.getLogger('joborders_sync')
if not _log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
    _log.addHandler(h)
    _log.setLevel(logging.INFO)


# ─────────────────────────────────────────────────────────────────────
# Field extraction helpers
# ─────────────────────────────────────────────────────────────────────
# The ERP returns records with nested objects (equipment, status_group,
# repair_requests[], job_orders[]). These helpers do safe digging so the
# main loop stays readable.

def _g(d, *path, default=None):
    """Safe nested dict get. _g(obj, 'a', 'b') == obj['a']['b'] or default."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _derive_status(record):
    """Map an ERP record to our local BreakdownLog.status value.

    See module docstring for the rules. We try to be defensive — the
    record's shape may evolve, so we degrade gracefully to 'Under
    Repair' when anything looks off.
    """
    approver_status     = _g(record, 'status_group', 'approver_status',
                              default='').upper()
    maintenance_status  = _g(record, 'status_group', 'maintenance_approver_status',
                              default='').upper()

    # Either approval still pending → treat as Under Repair (we don't
    # yet model a separate "Pending Approval" state locally).
    if approver_status != 'APPROVED' or maintenance_status != 'APPROVED':
        return 'Under Repair'

    # All job_orders complete → Fixed
    jos = record.get('job_orders') or []
    if jos:
        all_done = all(
            (_g(jo, 'progress', 'total_done', default=0) >= 1
             and _g(jo, 'progress', 'total_done', default=0)
                 == _g(jo, 'progress', 'total_count', default=0))
            for jo in jos
        )
        if all_done:
            return 'Fixed'

    return 'Under Repair'


def _derive_description(record):
    """Concatenate all repair_requests[].issue into one description."""
    issues = record.get('repair_requests') or []
    parts = []
    for r in issues:
        text = (r.get('issue') or '').strip()
        if text:
            parts.append(text)
    return '; '.join(parts) if parts else None


def _derive_started_at(record):
    """Map ERP created_at → local started_at (the moment the truck went
    out of service from the dispatcher's perspective). Tries multiple
    common datetime field shapes."""
    raw = record.get('created_at') or record.get('createdAt')
    if not raw:
        return None
    try:
        # Common shapes: 'YYYY-MM-DD HH:MM:SS' or ISO with 'T'
        return datetime.fromisoformat(raw.replace(' ', 'T'))
    except (ValueError, TypeError):
        return None


def _derive_ended_at(record):
    """Pick the latest 'complete' transaction timestamp as ended_at.

    The ERP's transactions[] array holds the audit trail. We look for
    entries whose description signals completion. If we can't find one,
    return None — the row stays open.
    """
    txns = record.get('transactions') or []
    candidates = []
    for t in txns:
        desc = (t.get('description') or '').lower()
        if 'complete' in desc or 'released' in desc:
            ts = t.get('created_at') or t.get('action_at') or t.get('timestamp')
            if ts:
                try:
                    candidates.append(
                        datetime.fromisoformat(ts.replace(' ', 'T')))
                except (ValueError, TypeError):
                    pass
    return max(candidates) if candidates else None


def _match_plate(ref_no, Plate):
    """Find the local Plate that corresponds to an ERP equipment ref_no.

    The ERP uses a body-number-style code (e.g., 'D26E06'). Our local
    Plate model has body_no and plate_no. We try body_no first (the
    expected match), then plate_no as a fallback. Return None if no
    match — the BreakdownLog row will still be created with plate_id=NULL
    and a warning logged, so a fleet manager can link it manually later.
    """
    if not ref_no:
        return None
    ref_no = ref_no.strip().upper()
    # Try body_no exact match first
    p = Plate.query.filter(
        db_func_upper(Plate.body_no) == ref_no,
        Plate.active.is_(True),
    ).first()
    if p:
        return p
    # Fallback: plate_no exact match
    p = Plate.query.filter(
        db_func_upper(Plate.plate_no) == ref_no,
        Plate.active.is_(True),
    ).first()
    return p


def db_func_upper(col):
    """Tiny adapter so we can pass either a SQLAlchemy Column or a string
    to UPPER(). Saves an import inside the matcher hotpath."""
    from sqlalchemy import func
    return func.upper(col)


# ─────────────────────────────────────────────────────────────────────
# Main sync routine
# ─────────────────────────────────────────────────────────────────────

def run_sync(app=None, log=None, filter='', from_date=None, to_date=None):
    """Run one sync iteration.

    Args:
        app:       Flask app instance. If None, imports app_v3.
        log:       optional logger override.
        filter:    '' (all), 'pending', 'approved', 'rejected'. Default ''.
        from_date: optional 'YYYY-MM-DD' string. If None, defaults to 7
                   days ago (initial bootstrap window).
        to_date:   optional 'YYYY-MM-DD' string. Defaults to today.

    Returns:
        dict with summary stats.
    """
    log = log or _log

    if app is None:
        import app_v3
        app = app_v3.app

    # Sensible defaults for the date window. The ERP list endpoint
    # supports from/to filters per the Postman collection, so we use
    # them to bound the polling window — keeps the response small even
    # if the ERP has years of history.
    today = utc_now().date()
    if to_date is None:
        to_date = today.isoformat()
    if from_date is None:
        from_date = (today - timedelta(days=7)).isoformat()

    summary = {
        'polled_at':        utc_now().isoformat() + 'Z',
        'configured':       False,
        'records_fetched':  0,
        'created':          0,
        'updated':          0,
        'plate_unmatched':  0,
        'errors':           [],
    }

    with app.app_context():
        from models_v2 import db, Plate, BreakdownLog
        from joborders_client import JobOrdersClient

        cc = JobOrdersClient.from_env()
        summary['configured'] = cc.configured
        if not cc.configured:
            summary['errors'].append('JOBORDERS_TOKEN not set in env')
            log.warning('JobOrders not configured — skipping')
            return summary

        # ── Fetch the list ───────────────────────────────────────────
        data, err = cc.list_repair_requests(
            filter=filter, from_date=from_date, to_date=to_date)
        if err:
            summary['errors'].append(err)
            log.error('list_repair_requests failed: %s', err)
            return summary

        # Unwrap the response. The ERP returns a Laravel paginator
        # nested inside the outer envelope. Observed shape (May 30 2026):
        #
        #   {
        #     "data": {                         ← outer envelope
        #         "current_page": 1,
        #         "data": [ {...}, {...}, ...], ← actual records here
        #         "first_page_url": "...",
        #         "from": 1,
        #         "last_page": 1,
        #         "last_page_url": "...",
        #         "links": [...],
        #         "next_page_url": null,
        #         "path": "...",
        #         "per_page": 15,
        #         "prev_page_url": null,
        #         "to": 13,
        #         "total": 13
        #     },
        #     "count": 13,
        #     "message": "..."
        #   }
        #
        # We dig two levels: outer.data → paginator → paginator.data.
        # If the API ever flattens to {data: [...]} (no paginator),
        # the second dig is a no-op because the first .get already
        # returned an array.
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get('data') or data.get('items') or []
            # Unwrap Laravel paginator: {current_page, data, total, ...}
            if (isinstance(records, dict)
                    and 'data' in records
                    and isinstance(records.get('data'), list)):
                records = records['data']
        else:
            summary['errors'].append(f'unexpected response type {type(data).__name__}')
            log.error('unexpected response type: %s', type(data).__name__)
            return summary

        summary['records_fetched'] = len(records)
        log.info('Fetched %d records (filter=%r, from=%s, to=%s)',
                 len(records), filter, from_date, to_date)

        # ── Upsert each record ───────────────────────────────────────
        # Observed in production (May 30 2026): the /list endpoint
        # returns shallow items — each entry in data[] is just the
        # repair-request id as a string/int, NOT a full record dict.
        # So we have to follow up with a /show call per item to get
        # the equipment / status / approval details we need to upsert.
        #
        # If a future API version returns full dicts in /list, the
        # isinstance(rec_item, dict) branch will pick them up
        # transparently — no further changes needed.
        now = utc_now()
        for rec_item in records:
            ext_id = None
            try:
                if isinstance(rec_item, dict):
                    # /list returned full records — use as-is
                    rec = rec_item
                    ext_id = rec.get('id')
                else:
                    # /list returned just an ID — fetch the full record
                    try:
                        ext_id = int(rec_item)
                    except (TypeError, ValueError):
                        log.warning('Skipping non-numeric list item: %r', rec_item)
                        continue
                    show_response, err = cc.get_repair_request(ext_id)
                    if err:
                        summary['errors'].append(f'show id={ext_id}: {err}')
                        log.warning('get_repair_request #%s failed: %s', ext_id, err)
                        continue
                    # /show returns {data: {...}, message: "maintenanceRequest.show"}
                    if isinstance(show_response, dict):
                        rec = show_response.get('data') or show_response
                    else:
                        log.warning('Unexpected /show response for #%s: %r',
                                    ext_id, show_response)
                        continue

                if not ext_id:
                    log.warning('Skipping record with no id: %r', rec)
                    continue

                # Find existing local row by external ID, or create a new one.
                # CRITICAL: BreakdownLog.date is NOT NULL. We must seed it
                # at construction time, because subsequent Plate.query calls
                # in this iteration trigger SQLAlchemy autoflush — and a
                # flush with date=NULL would raise IntegrityError, killing
                # this whole transaction. We use today's date as a safe
                # default; if the record carries a real created_at later
                # below, row.date is overwritten with that value.
                row = BreakdownLog.query.filter_by(jo_external_id=ext_id).first()
                is_new = row is None
                if is_new:
                    row = BreakdownLog(jo_external_id=ext_id,
                                       date=now.date())
                    db.session.add(row)

                # Plate matching
                ref_no = rec.get('ref_no') or ''
                plate = _match_plate(ref_no, Plate)
                if plate is None and ref_no:
                    summary['plate_unmatched'] += 1
                    log.warning('No plate match for ref_no=%r (record id=%s)',
                                ref_no, ext_id)

                # Populate / refresh fields
                row.plate_id                = plate.id if plate else None
                row.jo_ref_no               = ref_no or None
                row.equipment_name          = _g(rec, 'equipment', 'name')
                row.equipment_brand         = _g(rec, 'equipment', 'brand')
                row.operator_name           = rec.get('operator_name')
                row.requested_by            = rec.get('prepared_by')
                row.approved_by_dispatcher  = rec.get('approved_by')
                row.approved_by_maintenance = rec.get('maintenance_approved_by')

                row.description = _derive_description(rec) or row.description
                started = _derive_started_at(rec)
                ended   = _derive_ended_at(rec)
                if started:
                    row.started_at = started
                    if not row.date:
                        row.date = started.date()
                if ended:
                    row.ended_at = ended
                    row.resolved_date = ended.date()
                if not row.date:
                    row.date = now.date()

                row.status = _derive_status(rec)

                # Best-effort deep link back to the ERP UI (the user-
                # facing path, not the API path). The repair-request
                # detail page sits at https://erp.gainersand.ph/...
                row.jo_url = f'https://erp.gainersand.ph/repair-request/manage/{ext_id}'

                row.last_synced_at = now
                row.updated_by     = 'erp_sync'

                if is_new:
                    summary['created'] += 1
                else:
                    summary['updated'] += 1
            except Exception as e:
                # Use ext_id captured above so we don't crash here if
                # rec is itself the offending value (e.g., string id
                # that failed type conversion).
                #
                # Rollback the session so the NEXT record's queries can
                # run cleanly. Without this, every subsequent upsert
                # cascades-fails with "This Session's transaction has
                # been rolled back due to a previous exception", masking
                # the real cause and producing 13× the same error.
                summary['errors'].append(f'upsert id={ext_id}: {e}')
                log.exception('upsert failed for record id=%s', ext_id)
                try:
                    db.session.rollback()
                except Exception:
                    pass
                continue

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            summary['errors'].append(f'commit failed: {e}')
            log.exception('db commit failed')

    return summary


# ─────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────
# Usage:
#   python joborders_sync.py             — one-shot sync, prints summary
#   python joborders_sync.py --loop      — repeat every 600 seconds (10 min)
#   python joborders_sync.py --loop 300  — repeat every 300 seconds (5 min)
# ─────────────────────────────────────────────────────────────────────

def _run_loop(interval_seconds=600):
    """Long-running poll loop for use as a PA Always-On task."""
    import time
    print(f'[joborders-loop] starting (interval={interval_seconds}s)', flush=True)
    iteration = 0
    while True:
        iteration += 1
        started = time.time()
        try:
            summary = run_sync()
            elapsed = time.time() - started
            print(f'[#{iteration}] {utc_now().isoformat()}Z '
                  f'elapsed={elapsed:.1f}s '
                  f'fetched={summary.get("records_fetched", 0)} '
                  f'created={summary.get("created", 0)} '
                  f'updated={summary.get("updated", 0)} '
                  f'unmatched={summary.get("plate_unmatched", 0)} '
                  f'errors={len(summary.get("errors", []))}',
                  flush=True)
            if summary.get('errors'):
                for err in summary['errors'][:2]:
                    print(f'  ERR: {err}', flush=True)
        except KeyboardInterrupt:
            print('[joborders-loop] interrupt — exiting cleanly', flush=True)
            return
        except Exception as e:
            import traceback
            elapsed = time.time() - started
            print(f'[#{iteration}] EXCEPTION after {elapsed:.1f}s: {e}', flush=True)
            traceback.print_exc()

        sleep_for = max(5.0, interval_seconds - (time.time() - started))
        time.sleep(sleep_for)


if __name__ == '__main__':
    import json
    if len(sys.argv) > 1 and sys.argv[1] == '--loop':
        try:
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 600
        except (ValueError, IndexError):
            interval = 600
        _run_loop(interval_seconds=interval)
    else:
        result = run_sync()
        print(json.dumps(result, indent=2, default=str))
        if result.get('errors'):
            sys.exit(1)
