"""Toll-event backfill from Cartrack's /rest/vehicles/events endpoint.

The polling worker (cartrack_poll.py) detects toll plaza transits in real
time by sampling /rest/vehicles/status every 60 seconds. At highway speed
a truck transits a 200-500m plaza zone in 7-14 seconds, so a 60-second
poll has roughly a 1-in-5 chance of catching the truck mid-transit. We
miss the remaining ~80% of brief transits — they slip between polls and
never produce ENTER/EXIT events.

This module closes that gap by pulling Cartrack's server-side event log,
which captures EVERY geofence enter/exit moment (their backend processes
continuous GPS, not 60s snapshots). For each event involving a
toll-category geofence, we check whether the polling worker already
recorded a matching CartrackEvent row — if not, we create one.

Run cadence: every ~30 minutes (piggybacked onto the Cartrack always-on
task, similar to the JobOrders sync). At that cadence the lookback
window is small (~31 min) so the API response stays compact.

Designed to be SAFE TO RE-RUN: every insert is preceded by a duplicate
check on (plate_id, plaza_name, event_type, created_at within 90s).
Running twice over the same period is idempotent.
"""
import logging
import os
import sys
from datetime import datetime, timedelta

# Naive-UTC helper (drop-in replacement for datetime.utcnow).
from models_v2 import utc_now

# Make this module importable both standalone and from within Flask.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# Re-use cartrack_poll's plaza-name cleanup so a backfilled event's
# plaza_name uses the same canonical form as the live-polled ones
# (otherwise the same plaza would appear under two different names
# in the Toll Log table).
def _get_clean_plaza_name(geofence_name):
    from cartrack_poll import _strip_toll_prefix
    return _strip_toll_prefix(geofence_name)


# Logger
_log = logging.getLogger('cartrack_trips_backfill')
if not _log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
    _log.addHandler(h)
    _log.setLevel(logging.INFO)


# Dedup window: when scanning Cartrack events, treat any local
# CartrackEvent within DEDUP_SECONDS of the Cartrack event as the
# "same" transit (since the live-poll path and the backfill path may
# stamp the row at slightly different moments — live-poll uses
# server clock at poll time, backfill uses Cartrack's reported event
# timestamp).
DEDUP_SECONDS = 90


def _parse_cartrack_ts(raw):
    """Parse a Cartrack event timestamp into a naive UTC datetime.

    Cartrack PH returns timestamps in PHT (Asia/Manila wall time) as
    naive strings — e.g., '2026-05-30 14:23:35'. We strip the implied
    PHT offset (UTC+8) so the result lines up with the naive-UTC values
    we store everywhere else.

    Returns None on parse failure.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace(' ', 'T'))
    except (ValueError, TypeError):
        return None
    # If tz-aware (rare), drop the tz info after converting to UTC.
    if dt.tzinfo is not None:
        from datetime import timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    # Naive — Cartrack PH treats these as Asia/Manila local. Subtract 8h
    # to get naive UTC, matching our storage convention.
    return dt - timedelta(hours=8)


def backfill_toll_events(app=None, lookback_minutes=35, log=None):
    """Backfill missed toll ENTER/EXIT events from Cartrack's event log.

    Args:
        app:              Flask app instance. If None, imports app_v3.
        lookback_minutes: How far back to scan. Default 35 — slightly
                          longer than the 30-min schedule cadence so we
                          have overlap and never miss a transit at the
                          window boundary.
        log:              optional logger override.

    Returns:
        dict with summary stats {scanned, backfilled, skipped_dup,
        skipped_non_toll, errors}.
    """
    log = log or _log
    if app is None:
        import app_v3
        app = app_v3.app

    summary = {
        'polled_at':         utc_now().isoformat() + 'Z',
        'lookback_minutes':  lookback_minutes,
        'configured':        False,
        'events_scanned':    0,
        'toll_events_seen':  0,
        'backfilled':        0,
        'skipped_dup':       0,
        'skipped_non_toll':  0,
        'errors':            [],
    }

    with app.app_context():
        from models_v2 import db, Plate, CartrackGeofence, CartrackEvent
        from cartrack_client import CartrackClient

        cc = CartrackClient.from_env()
        summary['configured'] = cc.configured
        if not cc.configured:
            summary['errors'].append('Cartrack not configured')
            return summary

        # ── 1. Fetch events in the lookback window ──────────────────
        # Use PHT-aware "now" because cartrack_client.get_events
        # formats timestamps as Asia/Manila wall time.
        try:
            from zoneinfo import ZoneInfo
            now_pht = datetime.now(ZoneInfo('Asia/Manila'))
        except Exception:
            now_pht = utc_now() + timedelta(hours=8)
        start_dt = now_pht - timedelta(minutes=lookback_minutes)
        end_dt   = now_pht

        events, err = cc.get_events(start_dt=start_dt, end_dt=end_dt)
        if err:
            # get_events now returns partial pages alongside the error
            # (e.g. rate-limited midway). Log it, but only bail when we
            # truly got nothing — partial results still backfill real
            # transits and the dedup window makes re-processing safe.
            summary['errors'].append(f'get_events failed: {err}')
            log.error('get_events failed: %s', err)
            if not events:
                return summary
            log.warning('continuing with %d events from partial scan',
                        len(events))
        summary['events_scanned'] = len(events or [])

        # ── 2. Build lookup tables once ─────────────────────────────
        # vehicle_id -> Plate (only mapped plates matter)
        plates = (Plate.query
                  .filter(Plate.active.is_(True),
                          Plate.cartrack_vehicle_id.isnot(None))
                  .all())
        plate_by_vid = {p.cartrack_vehicle_id: p for p in plates}

        # cartrack_id -> CartrackGeofence (only toll-category geofences)
        toll_gfs = CartrackGeofence.query.filter_by(category='toll').all()
        toll_gf_by_cartrack_id = {g.cartrack_id: g for g in toll_gfs}

        # ── 3. Process each event ───────────────────────────────────
        for evt in (events or []):
            try:
                # The exact shape of /rest/vehicles/events isn't formally
                # documented, but field naming follows the rest of the
                # Cartrack API. Adjust here if a sample run reveals
                # different keys.
                vehicle_id = evt.get('vehicle_id') or evt.get('vehicleId')
                event_type = (evt.get('event_type') or evt.get('eventType')
                               or evt.get('type') or '').lower()
                gf_cartrack_id = (evt.get('geofence_id')
                                   or evt.get('geofenceId')
                                   or _g(evt, 'geofence', 'id'))
                evt_ts_raw = (evt.get('event_timestamp')
                               or evt.get('eventTimestamp')
                               or evt.get('timestamp')
                               or evt.get('created_at'))
                lat = evt.get('latitude') or _g(evt, 'location', 'latitude')
                lng = evt.get('longitude') or _g(evt, 'location', 'longitude')

                # Filter: must be a geofence enter/exit event with a
                # known toll-category geofence and a mapped plate.
                norm_type = None
                if 'enter' in event_type or event_type in ('entered', 'in'):
                    norm_type = 'enter'
                elif 'exit' in event_type or event_type in ('exited', 'out'):
                    norm_type = 'exit'

                if norm_type is None:
                    continue   # not a geofence event

                gf = toll_gf_by_cartrack_id.get(gf_cartrack_id)
                if gf is None:
                    summary['skipped_non_toll'] += 1
                    continue   # geofence isn't a toll plaza

                summary['toll_events_seen'] += 1

                plate = plate_by_vid.get(vehicle_id)
                if plate is None:
                    continue   # plate not mapped — same policy as live poll

                evt_ts = _parse_cartrack_ts(evt_ts_raw)
                if not evt_ts:
                    log.warning('Skipping event with unparseable ts: %r', evt_ts_raw)
                    continue

                plaza_name = _get_clean_plaza_name(gf.name)
                if not plaza_name:
                    continue

                # ── 4. Dedup check ──────────────────────────────────
                # If a CartrackEvent already exists for this plate +
                # plaza + event_type within DEDUP_SECONDS of evt_ts,
                # the live polling worker (or a previous backfill run)
                # already captured this transit. Skip it.
                window_start = evt_ts - timedelta(seconds=DEDUP_SECONDS)
                window_end   = evt_ts + timedelta(seconds=DEDUP_SECONDS)
                exists = (CartrackEvent.query.filter(
                            CartrackEvent.plate_id   == plate.id,
                            CartrackEvent.plaza_name == plaza_name,
                            CartrackEvent.event_type == norm_type,
                            CartrackEvent.created_at >= window_start,
                            CartrackEvent.created_at <= window_end,
                        ).first())
                if exists:
                    summary['skipped_dup'] += 1
                    continue

                # ── 5. Insert the backfilled event ──────────────────
                db.session.add(CartrackEvent(
                    plate_id   = plate.id,
                    event_type = norm_type,
                    plaza_name = plaza_name,
                    expressway = None,   # cartrack event doesn't carry this
                    lat        = lat,
                    lng        = lng,
                    created_at = evt_ts,
                    notes      = 'backfilled from /rest/vehicles/events',
                ))
                summary['backfilled'] += 1
                log.info('[BACKFILL] %s %s at %s (%s) — was missed by live poll',
                          plate.display, norm_type.upper(), plaza_name,
                          evt_ts.isoformat())
            except Exception as e:
                summary['errors'].append(f'event processing failed: {e}')
                log.exception('event processing failed for event: %r', evt)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            summary['errors'].append(f'commit failed: {e}')
            log.exception('db commit failed')

    return summary


def _g(d, *path, default=None):
    """Safe nested dict get."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


# ─────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────
# Use this once to see what /rest/vehicles/events actually returns from
# Cartrack PH, so we can validate field naming assumptions above.
#
#   python -c "from cartrack_trips_backfill import _smoke; _smoke()"
#
# Output is sanitised — keys only, no values — so it can be shared
# safely if needed for further analysis.

def _smoke():
    """Show the response shape of /rest/vehicles/events for a 1-hour window."""
    try:
        from cartrack_poll import _bootstrap_env_from_wsgi
        _bootstrap_env_from_wsgi()
    except Exception:
        pass

    from cartrack_client import CartrackClient
    cc = CartrackClient.from_env()
    print(f'configured = {cc.configured}')
    if not cc.configured:
        return

    events, err = cc.get_events()
    if err:
        print(f'ERR: {err}')
        return
    print(f'events returned: {len(events or [])}')
    if not events:
        print('(no events in the last hour — try a busier time window)')
        return

    # Show the keys of the first event so we can validate field names
    first = events[0]
    print('\nFirst event keys (top level):')
    for k in sorted(first.keys()):
        v = first[k]
        type_name = type(v).__name__
        if isinstance(v, dict):
            sub_keys = sorted(v.keys())
            print(f'  {k}: {type_name} {sub_keys}')
        else:
            print(f'  {k}: {type_name}')

    # Count by event_type so we can see what types Cartrack emits
    type_counts = {}
    for e in events:
        et = (e.get('event_type') or e.get('eventType')
              or e.get('type') or '<missing>').lower()
        type_counts[et] = type_counts.get(et, 0) + 1
    print('\nEvent types in this window:')
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f'  {t}: {c}')


# ─────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────
# Usage:
#   python cartrack_trips_backfill.py             — one-shot backfill
#   python cartrack_trips_backfill.py --lookback 120  — scan last 120 min
#   python cartrack_trips_backfill.py --smoke    — inspect API response shape
# ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import json
    if len(sys.argv) > 1 and sys.argv[1] == '--smoke':
        _smoke()
    else:
        # Parse optional --lookback arg
        lookback = 35
        if '--lookback' in sys.argv:
            try:
                idx = sys.argv.index('--lookback')
                lookback = int(sys.argv[idx + 1])
            except (ValueError, IndexError):
                pass
        result = backfill_toll_events(lookback_minutes=lookback)
        print(json.dumps(result, indent=2, default=str))
        if result.get('errors'):
            sys.exit(1)
