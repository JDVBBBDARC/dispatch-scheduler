"""
Cartrack polling worker — detects toll plaza crossings and auto-fills toll_fee.

This module is callable as a standalone script (via PythonAnywhere Scheduled
Task or cron) AND as a function from within the Flask app (for manual triggers).

Algorithm:
    1. Fetch all vehicle positions from Cartrack
    2. For each truck mapped to a Plate.cartrack_vehicle_id:
        a. Compute distance from current GPS to every toll plaza coordinate
        b. Determine which plazas the truck is currently inside (radius_m check)
        c. Diff vs. last known state (from CartrackTruckState):
             new plazas in list  -> ENTER events
             plazas no longer in list -> EXIT events
        d. Update trip-tracking state:
             First ENTER opens a new trip-tracking session (toll_entry candidate)
             Subsequent ENTERs update toll_exit candidate
        e. Save new state
    3. Close trip-tracking sessions idle for >= 30 min:
        - Look up the matching open TripRecord for the plate (today, not yet
          delivered, no toll_fee set yet)
        - Compute toll fee from entry -> exit via toll_rates.json BFS routing
        - Set TripRecord.toll_fee, toll_entry, toll_exit, toll_expressway
        - Log a CartrackEvent of type 'trip_closed'

Storage strategy:
    - No raw API response caching (in-memory only)
    - CartrackTruckState: small, fixed-size (1 row per plate)
    - CartrackEvent: audit log, auto-pruned to last 60 days
"""
import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

# Make the module importable both standalone and from within the Flask app
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _bootstrap_env_from_wsgi():
    """Populate os.environ with `os.environ[...] = ...` lines from the WSGI file.

    On PythonAnywhere, env vars defined in the WSGI config file are only
    visible to the web-app process. Always-On Tasks run as a *separate*
    process with a fresh environment, so they don't see CARTRACK_USERNAME,
    CARTRACK_PASSWORD, etc. — which makes CartrackClient.from_env() fail
    with 'not configured'.

    To make tasks self-sufficient, we parse the WSGI file at module load
    time and copy any `os.environ['KEY'] = 'value'` statements into our
    own environment. Already-set env vars are NOT overwritten, so this
    is safe to run in any context (Flask web app, console, task).

    Looks for the WSGI file at the conventional PythonAnywhere path:
        /var/www/<username>_pythonanywhere_com_wsgi.py

    Silently skipped if the file isn't found (e.g., running locally).
    """
    try:
        # Find the WSGI file. PA convention: /var/www/<user>_pythonanywhere_com_wsgi.py
        import glob
        candidates = glob.glob('/var/www/*_pythonanywhere_com_wsgi.py')
        if not candidates:
            return   # not on PA, or unconventional location
        with open(candidates[0]) as f:
            for line in f:
                stripped = line.strip()
                # Only execute lines that look like `os.environ['X'] = '...'`
                # Skip anything else (imports, comments, sys.path manipulation, etc.)
                # to keep the bootstrap surface small and safe.
                if stripped.startswith('os.environ[') and '=' in stripped:
                    try:
                        # Execute the assignment in a controlled namespace
                        local_env = {'os': os}
                        exec(stripped, local_env)
                    except Exception:
                        pass   # ignore malformed lines
    except Exception:
        # Never let env bootstrap kill the task — fall back to whatever
        # env vars are already set.
        pass


# Run env bootstrap at module import time so it's ready before any
# CartrackClient.from_env() call.
_bootstrap_env_from_wsgi()


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

# How long a trip can be idle before we consider it "closed" and compute toll
TRIP_IDLE_CLOSE_MINUTES = 30

# How many days of CartrackEvent log to keep
EVENT_RETENTION_DAYS = 60

# Polling interval in seconds. Used to accumulate idling time per poll.
# Should match the --loop argument passed to cartrack_poll.py (default 60s).
# If you change the loop interval, update this too — otherwise idling stats
# will be over- or under-counted by the same ratio.
POLL_INTERVAL_SECONDS = 60

# Stale-cycle auto-close: if a cycle has been open for this long without
# the truck returning to home, we flag it as a 'long' cycle but keep it
# open (in case the truck is on a real multi-day trip). After this many
# days though, we hard-close it as 'abandoned' so the open-cycle count
# doesn't grow forever.
CYCLE_HARD_CLOSE_DAYS = 14

# Minimum dwell time (in minutes) for a SiteVisit to be considered a
# 'real' delivery/pickup stop. Anything shorter is marked is_drive_by=True
# and hidden from the UI by default. Helps filter out:
#   - Trucks passing through a geofence on a road that overlaps with one
#   - Brief touch-and-go (e.g., u-turn at the edge of a customer site)
#   - GPS jitter that briefly puts a truck inside a fence
# Set to 5 min based on real-world observation; raise to 10 min if you
# want to be stricter, or 1-2 min if your geofences are tightly drawn.
MIN_VISIT_MINUTES = 5

# Whether to create SiteVisit rows for the HOME geofence (BIG BEN SCM).
# When False (recommended), the polling worker uses home enter/exit
# events ONLY to open/close TruckCycles, but doesn't clutter the visits
# table with "idle at home for 18 hours" rows — those aren't useful for
# delivery analytics. The cycle data itself captures total time away
# from home, which is the more meaningful metric.
TRACK_HOME_AS_VISIT = False

# Logger
_log = logging.getLogger('cartrack_poll')
if not _log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
    _log.addHandler(h)
    _log.setLevel(logging.INFO)


# ─────────────────────────────────────────────────────────────────────
# Geo math
# ─────────────────────────────────────────────────────────────────────

def haversine_meters(lat1, lng1, lat2, lng2):
    """Distance between two GPS points in meters."""
    R = 6_371_000.0
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat  = math.radians(lat2 - lat1)
    dlng  = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def load_plaza_coords():
    """Return list of {plaza, expressway, lat, lng, radius_m} from toll_rates.json."""
    path = os.path.join(_HERE, 'static', 'toll_rates.json')
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    plazas = []
    for exp_key, exp_data in data.items():
        coords = exp_data.get('coordinates') or {}
        for plaza, c in coords.items():
            plazas.append({
                'plaza':      plaza,
                'expressway': exp_key,
                'lat':        c['lat'],
                'lng':        c['lng'],
                'radius_m':   c.get('radius_m', 200),
            })
    return plazas


def find_plazas_at_position(lat, lng, plazas):
    """Return list of plaza dicts the position is currently inside."""
    if lat is None or lng is None:
        return []
    inside = []
    for p in plazas:
        if haversine_meters(lat, lng, p['lat'], p['lng']) <= p['radius_m']:
            inside.append(p)
    return inside


# ─────────────────────────────────────────────────────────────────────
# Toll fee computation — reuses the existing BFS routing
# ─────────────────────────────────────────────────────────────────────

def compute_toll_fee(entry_plaza, exit_plaza, toll_class='Class 3'):
    """Compute toll fee for entry -> exit. Returns (fee, expressway_key) or (None, None)."""
    path = os.path.join(_HERE, 'static', 'toll_rates.json')
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Try direct lookup in each expressway first
    for exp_key, exp_data in data.items():
        matrix = exp_data.get(toll_class, {})
        rate = (matrix.get(entry_plaza, {}).get(exit_plaza)
                or matrix.get(exit_plaza, {}).get(entry_plaza))
        if rate is not None:
            return float(rate), exp_key

    # Fallback to BFS multi-expressway routing (mirrors app_v3.find_toll_route)
    try:
        from app_v3 import find_toll_route
        cost, _segs = find_toll_route(entry_plaza, exit_plaza, toll_class, data)
        if cost is not None:
            return float(cost), 'multi'
    except Exception:
        pass
    return None, None


# ─────────────────────────────────────────────────────────────────────
# Geofence sync + categorization
# ─────────────────────────────────────────────────────────────────────

# Patterns used to auto-categorize Cartrack geofences by name.
# Order matters: first match wins, so put more-specific keywords first.
# All comparisons are case-insensitive against the geofence name.
_GEOFENCE_CATEGORY_PATTERNS = [
    # Home base — special case, the only one that sets is_home=True.
    ('home', [
        'BIG BEN SCM',
    ]),
    # Toll plazas — user manually drew geofences around booths in Cartrack.
    # Anything starting with "Toll" or containing common booth names.
    ('toll', [
        'TOLL ',  # e.g., "Toll - Bocaue", "Toll - Pulilan"
        'TOLLBOOTH',
        'TOLL PLAZA',
    ]),
    # Fuel / service stations
    ('fuel', [
        'SHELL',
        'PETRON',
        'CALTEX',
        'PHOENIX',
        'TOTAL',
        'SEAOIL',
        'DIESEL',     # generic diesel stations
        'GAS STATION',
        'GASOLINE',
    ]),
    # Quarries / aggregate suppliers
    ('quarry', [
        'QUARRY',
    ]),
    # Internal operations / monitoring zones
    ('operations', [
        'WEIGHING SCALE',
        'WEIGH STATION',
        'URINE STATION',
        'INSPECTION',
    ]),
    # Construction / customer sites — broad catch for typical project keywords
    ('customer', [
        'CONSTRUCTION',
        'BUILDERS',
        'CONCRETE',
        'CEMENT',
        'READYMIX',
        'STEEL STRUCTURE',
        'RECYCLABLES',
        'RENEWWABLE',
        'RENEWABLE',
    ]),
]


def _categorize_geofence(name):
    """Return (category, is_home) tuple for a geofence name.

    Falls back to 'other' / False if no pattern matches.
    """
    if not name:
        return 'other', False
    upper = name.upper()
    for category, keywords in _GEOFENCE_CATEGORY_PATTERNS:
        for kw in keywords:
            if kw in upper:
                return category, (category == 'home')
    return 'other', False


def sync_geofences(app=None, log=None):
    """Pull every geofence from Cartrack and cache it in CartrackGeofence.

    Idempotent — uses cartrack_id (Cartrack's UUID) as the unique key.
    Updates name/description/polygon on each run so admin-side edits in
    Cartrack flow back to the app.

    Newly-created rows get an auto-assigned category and is_home flag
    based on their name; existing rows keep their (possibly manually
    edited) category unless their name changes.

    Returns a summary dict.
    """
    if log is None:
        log = logging.getLogger('cartrack_geofence_sync')

    if app is None:
        import app_v3 as _app_module
        app = _app_module.app

    summary = {
        'configured':       False,
        'total_fetched':    0,
        'created':          0,
        'updated':          0,
        'name_changed':     0,
        'recategorized':    0,
        'errors':           [],
    }

    with app.app_context():
        from models_v2 import db, CartrackGeofence
        from cartrack_client import CartrackClient

        cc = CartrackClient.from_env()
        summary['configured'] = cc.configured
        if not cc.configured:
            summary['errors'].append('Cartrack not configured (env vars missing)')
            return summary

        geofences, err = cc.list_geofences()
        if err:
            summary['errors'].append(f'list_geofences failed: {err}')
            return summary

        summary['total_fetched'] = len(geofences or [])
        now = datetime.utcnow()

        for g in (geofences or []):
            cartrack_id = (g.get('geofence_id') or '').strip()
            name        = (g.get('name') or '').strip()
            if not cartrack_id or not name:
                continue   # skip malformed entries

            existing = (CartrackGeofence.query
                        .filter_by(cartrack_id=cartrack_id)
                        .first())

            if existing is None:
                # New geofence — categorize and insert
                category, is_home = _categorize_geofence(name)
                row = CartrackGeofence(
                    cartrack_id          = cartrack_id,
                    name                 = name,
                    description          = g.get('description') or '',
                    position_description = g.get('position_description') or '',
                    colour               = g.get('colour') or '',
                    polygon_wkt          = g.get('polygon') or '',
                    category             = category,
                    is_home              = is_home,
                    last_synced_at       = now,
                )
                db.session.add(row)
                summary['created'] += 1
                log.info('[sync] CREATE %s (category=%s, is_home=%s)',
                         name, category, is_home)
            else:
                # Existing — refresh fields, re-categorize if name changed
                if existing.name != name:
                    summary['name_changed'] += 1
                    new_cat, new_home = _categorize_geofence(name)
                    if new_cat != existing.category:
                        summary['recategorized'] += 1
                        existing.category = new_cat
                        existing.is_home  = new_home
                    existing.name = name
                existing.description          = g.get('description') or existing.description
                existing.position_description = g.get('position_description') or existing.position_description
                existing.colour               = g.get('colour') or existing.colour
                existing.polygon_wkt          = g.get('polygon') or existing.polygon_wkt
                existing.last_synced_at       = now
                summary['updated'] += 1

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            summary['errors'].append(f'commit failed: {e}')

    return summary


# ─────────────────────────────────────────────────────────────────────
# Main polling routine
# ─────────────────────────────────────────────────────────────────────

def run_poll(app=None, log=None):
    """One iteration of the polling loop.

    Args:
        app:  Flask app instance (if calling from within Flask process).
              If None, imports app_v3 and uses its app.
        log:  optional logger override.

    Returns:
        dict with summary stats.
    """
    log = log or _log

    # Get the Flask app context
    if app is None:
        import app_v3
        app = app_v3.app

    summary = {
        'polled_at':      datetime.utcnow().isoformat() + 'Z',
        'configured':     False,
        'cartrack_ok':    False,
        'vehicles_seen':  0,
        'plates_tracked': 0,
        'plates_unmapped': 0,
        # Toll plaza tracking (existing)
        'enters_detected': 0,
        'exits_detected':  0,
        'trips_closed':    0,
        'toll_fees_filled': 0,
        # Cartrack-side geofence tracking (new — site visits + cycles)
        'site_visits_opened': 0,
        'site_visits_closed': 0,
        'cycles_opened':      0,
        'cycles_closed':      0,
        'idle_seconds_logged': 0,
        'errors':         [],
    }

    with app.app_context():
        from models_v2 import (db, Plate, TripRecord, Wave, CartrackTruckState,
                                CartrackEvent, CartrackGeofence, SiteVisit,
                                TruckCycle)
        from cartrack_client import CartrackClient

        # ── 1. Set up Cartrack client ────────────────────────────────
        cc = CartrackClient.from_env()
        summary['configured'] = cc.configured
        if not cc.configured:
            summary['errors'].append('CARTRACK_USERNAME/PASSWORD not set in env')
            log.warning('Cartrack not configured — skipping')
            return summary

        # ── 2. Fetch all vehicle positions ───────────────────────────
        statuses, err = cc.get_status()
        if err:
            summary['errors'].append(f'get_status failed: {err}')
            log.error('Cartrack API call failed: %s', err)
            return summary
        summary['cartrack_ok'] = True
        summary['vehicles_seen'] = len(statuses)

        # Build vehicle_id -> status map
        by_vid = {s.get('vehicle_id'): s for s in statuses if s.get('vehicle_id')}

        # ── 3. Load all mapped plates ────────────────────────────────
        mapped_plates = Plate.query.filter(
            Plate.active == True,
            Plate.cartrack_vehicle_id.isnot(None),
        ).all()
        summary['plates_unmapped'] = (
            Plate.query.filter(Plate.active == True,
                               Plate.cartrack_vehicle_id.is_(None)).count()
        )

        # ── 4. Load plaza coordinates once ───────────────────────────
        plazas = load_plaza_coords()
        now = datetime.utcnow()

        # ── 5. For each mapped plate, diff state and emit events ─────
        for plate in mapped_plates:
            status = by_vid.get(plate.cartrack_vehicle_id)
            if not status:
                continue  # no recent position for this truck

            loc = status.get('location') or {}
            lat = loc.get('latitude')
            lng = loc.get('longitude')

            # Find current plazas using GPS distance (NOT Cartrack geofence_ids)
            inside = find_plazas_at_position(lat, lng, plazas)
            current_set = {p['plaza'] for p in inside}

            # Load or create state row
            state = CartrackTruckState.query.filter_by(plate_id=plate.id).first()
            if state is None:
                state = CartrackTruckState(plate_id=plate.id, current_plazas='')
                db.session.add(state)
                db.session.flush()

            summary['plates_tracked'] += 1
            previous_set = set(filter(None, (state.current_plazas or '').split(',')))

            new_enters = current_set - previous_set
            new_exits  = previous_set - current_set

            # Update last position (always)
            if lat is not None and lng is not None:
                state.last_lat = lat
                state.last_lng = lng
                state.last_position_at = now

            # ── Handle ENTER events ──
            for plaza_name in new_enters:
                plaza_info = next((p for p in inside if p['plaza'] == plaza_name), None)
                expressway = plaza_info['expressway'] if plaza_info else None
                summary['enters_detected'] += 1

                # Update trip-tracking state
                if not state.entry_plaza:
                    state.entry_plaza = plaza_name
                state.last_plaza = plaza_name
                state.last_event_ts = now

                db.session.add(CartrackEvent(
                    plate_id=plate.id, event_type='enter',
                    plaza_name=plaza_name, expressway=expressway,
                    lat=lat, lng=lng,
                ))
                log.info('[ENTER] %s -> %s', plate.display, plaza_name)

            # ── Handle EXIT events ──
            for plaza_name in new_exits:
                summary['exits_detected'] += 1
                state.last_event_ts = now

                db.session.add(CartrackEvent(
                    plate_id=plate.id, event_type='exit',
                    plaza_name=plaza_name, expressway=None,
                    lat=lat, lng=lng,
                ))
                log.info('[EXIT]  %s -> %s', plate.display, plaza_name)

            # Save updated plaza membership
            state.current_plazas = ','.join(sorted(current_set))

            # ── 5b. CARTRACK-SIDE GEOFENCE TRACKING (sites + cycles) ──
            # Cartrack reports geofence_ids per truck in get_status, so we
            # don't recompute geometry — just diff vs. the open SiteVisits
            # we have for this plate.

            current_geofence_uuids = set(loc.get('geofence_ids') or [])
            current_geofences = []
            if current_geofence_uuids:
                current_geofences = (CartrackGeofence.query
                                      .filter(CartrackGeofence.cartrack_id.in_(current_geofence_uuids))
                                      .all())
            current_gf_local_ids = {g.id for g in current_geofences}
            gf_by_id = {g.id: g for g in current_geofences}

            # Previously inside = plate has open (unclosed) SiteVisits
            open_visits = (SiteVisit.query
                            .filter(SiteVisit.plate_id == plate.id,
                                    SiteVisit.exit_at.is_(None))
                            .all())
            previous_gf_local_ids = {v.geofence_id for v in open_visits}

            gf_new_enters = current_gf_local_ids - previous_gf_local_ids
            gf_new_exits  = previous_gf_local_ids - current_gf_local_ids
            gf_still_in   = current_gf_local_ids & previous_gf_local_ids

            # Truck-level idle state (Cartrack returns top-level 'idling' bool).
            is_idling = bool(status.get('idling', False))

            # Find a currently-open TruckCycle for this plate (if any).
            open_cycle = (TruckCycle.query
                          .filter(TruckCycle.plate_id == plate.id,
                                  TruckCycle.ended_at.is_(None))
                          .first())

            # ── 5b.1 CYCLE TRACKING (home entry/exit) ──────────────────
            # We use cycle state — not SiteVisits — as the source of truth
            # for "is this truck currently away from home?" This way the
            # logic works even when TRACK_HOME_AS_VISIT=False (we don't
            # create SiteVisit rows for the home geofence).
            home_gf = CartrackGeofence.query.filter_by(is_home=True).first()
            is_at_home_now  = bool(home_gf and home_gf.cartrack_id in current_geofence_uuids)
            was_at_home_prev = open_cycle is None   # no open cycle ⇒ was at home

            if is_at_home_now and not was_at_home_prev and open_cycle is not None:
                # Truck just RETURNED home → close the open cycle.
                open_cycle.ended_at = now
                open_cycle.duration_minutes = max(
                    1, int((now - open_cycle.started_at).total_seconds() / 60))
                h = open_cycle.duration_minutes / 60.0
                open_cycle.category = (
                    'short'    if h < 12 else
                    'standard' if h < 24 else
                    'long'
                )
                summary['cycles_closed'] += 1
                log.info('[CYCLE-END] %s: cycle #%s duration=%.1fh (%s)',
                         plate.display, open_cycle.id, h, open_cycle.category)
                open_cycle = None
            elif not is_at_home_now and was_at_home_prev:
                # Truck just LEFT home → open a new cycle.
                new_cycle = TruckCycle(
                    plate_id   = plate.id,
                    started_at = now,
                    category   = 'ongoing',
                )
                db.session.add(new_cycle)
                db.session.flush()   # need cycle.id for subsequent SiteVisit links
                open_cycle = new_cycle
                summary['cycles_opened'] += 1
                log.info('[CYCLE-START] %s: cycle #%s', plate.display, new_cycle.id)

            # ── 5b.2 SITE VISITS for non-home geofences only ──────────
            # Home enter/exit is fully handled above; we explicitly skip
            # home in the loops below so trucks parked at the depot don't
            # generate phantom 18-hour "visits" cluttering the UI.
            home_id = home_gf.id if home_gf else None

            # Open new SiteVisits (skip home)
            for gf_id in gf_new_enters:
                if gf_id == home_id and not TRACK_HOME_AS_VISIT:
                    continue
                gf = gf_by_id.get(gf_id)
                if gf is None:
                    continue
                visit = SiteVisit(
                    plate_id        = plate.id,
                    geofence_id     = gf.id,
                    enter_at        = now,
                    idling_seconds  = POLL_INTERVAL_SECONDS if is_idling else 0,
                    cycle_id        = open_cycle.id if open_cycle else None,
                )
                db.session.add(visit)
                summary['site_visits_opened'] += 1
                log.info('[VISIT-IN ] %s -> %s (cycle=%s)',
                         plate.display, gf.name,
                         open_cycle.id if open_cycle else '-')

            # Close exited SiteVisits (drive-by flagged if too short)
            min_seconds = MIN_VISIT_MINUTES * 60
            for visit in open_visits:
                if visit.geofence_id not in gf_new_exits:
                    continue
                visit.exit_at = now
                duration = max(0, int((now - visit.enter_at).total_seconds()))
                visit.duration_seconds = duration
                if duration > 0:
                    visit.idling_pct = round(
                        100.0 * (visit.idling_seconds or 0) / duration, 1)
                visit.is_drive_by = duration < min_seconds
                summary['site_visits_closed'] += 1
                if visit.is_drive_by:
                    log.info('[VISIT-OUT] drive-by (%ds < %dmin threshold) %s',
                             duration, MIN_VISIT_MINUTES, plate.display)

            # Accumulate idling time for currently-inside visits
            if is_idling and gf_still_in:
                for visit in open_visits:
                    if visit.geofence_id in gf_still_in:
                        visit.idling_seconds = (visit.idling_seconds or 0) + POLL_INTERVAL_SECONDS
                        summary['idle_seconds_logged'] += POLL_INTERVAL_SECONDS

        db.session.commit()

        # ── 6. Close trips idle for >= 30 minutes ────────────────────
        idle_cutoff = now - timedelta(minutes=TRIP_IDLE_CLOSE_MINUTES)
        idle_states = CartrackTruckState.query.filter(
            CartrackTruckState.entry_plaza.isnot(None),
            CartrackTruckState.last_event_ts.isnot(None),
            CartrackTruckState.last_event_ts < idle_cutoff,
        ).all()

        for state in idle_states:
            entry = state.entry_plaza
            exit_plaza = state.last_plaza or state.entry_plaza
            if entry == exit_plaza:
                # Truck entered a plaza but didn't transit to another -
                # not a real trip (just passed through one booth). Clear state.
                log.info('[SKIP] %s: single-plaza touch %s — not a real trip',
                         state.plate.display if state.plate else state.plate_id, entry)
                state.entry_plaza   = None
                state.last_plaza    = None
                state.last_event_ts = None
                state.open_trip_id  = None
                continue

            # Compute toll fee
            fee, expressway = compute_toll_fee(entry, exit_plaza, 'Class 3')

            # Find matching open TripRecord (today, this truck, no toll yet)
            today = now.date()
            matching_trip = (
                db.session.query(TripRecord).join(Wave)
                .filter(Wave.date == today,
                        TripRecord.plate_id == state.plate_id,
                        TripRecord.status != 'Canceled',
                        (TripRecord.toll_fee.is_(None) | (TripRecord.toll_fee == 0)))
                .order_by(TripRecord.id)
                .first()
            )

            if matching_trip and fee is not None:
                matching_trip.toll_fee        = fee
                matching_trip.toll_entry      = entry
                matching_trip.toll_exit       = exit_plaza
                matching_trip.toll_expressway = expressway or ''
                matching_trip.toll_class      = 'Class 3'
                summary['toll_fees_filled'] += 1
                log.info('[FILL]  %s: trip #%s  %s -> %s = PHP %s (%s)',
                         state.plate.display if state.plate else state.plate_id,
                         matching_trip.id, entry, exit_plaza, fee, expressway)

            # Log trip_closed event
            db.session.add(CartrackEvent(
                plate_id=state.plate_id, event_type='trip_closed',
                plaza_name=None, expressway=expressway,
                trip_id=matching_trip.id if matching_trip else None,
                toll_fee=fee, toll_entry=entry, toll_exit=exit_plaza,
                notes=('no matching trip' if not matching_trip else
                       ('no rate found' if fee is None else 'auto-filled')),
            ))
            summary['trips_closed'] += 1

            # Reset state for next trip
            state.entry_plaza   = None
            state.last_plaza    = None
            state.last_event_ts = None
            state.open_trip_id  = None

        db.session.commit()

        # ── 7. Auto-prune old events ─────────────────────────────────
        cutoff = now - timedelta(days=EVENT_RETENTION_DAYS)
        deleted = db.session.query(CartrackEvent).filter(
            CartrackEvent.created_at < cutoff
        ).delete(synchronize_session=False)
        if deleted:
            log.info('[PRUNE] deleted %s old CartrackEvent rows', deleted)
        db.session.commit()

        # ── 8. Hard-close abandoned cycles ───────────────────────────
        # A cycle that's been "open" for > CYCLE_HARD_CLOSE_DAYS is almost
        # certainly stuck (truck sold, GPS broken, or boundary edge case).
        # Force-close so /api/cycle-time/summary doesn't accumulate fake
        # 'ongoing' cycles forever.
        stale_cutoff = now - timedelta(days=CYCLE_HARD_CLOSE_DAYS)
        stale_cycles = TruckCycle.query.filter(
            TruckCycle.ended_at.is_(None),
            TruckCycle.started_at < stale_cutoff,
        ).all()
        for sc in stale_cycles:
            sc.ended_at = now
            sc.duration_minutes = int((now - sc.started_at).total_seconds() / 60)
            sc.category = 'long'   # technically multi-day; flagged via notes elsewhere
        if stale_cycles:
            log.info('[PRUNE] force-closed %s abandoned cycles', len(stale_cycles))
            db.session.commit()

    return summary


# ─────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────

def _run_loop(interval_seconds=60):
    """Run run_poll() forever, sleeping between iterations.

    Intended for PythonAnywhere Always-On Tasks: PA keeps the process
    alive and restarts it on hard crash, so we just need a loop that
    polls, logs a compact one-line summary, and sleeps.

    Transient exceptions (Cartrack API hiccup, DB blip) are caught so
    they don't take the loop down — only KeyboardInterrupt exits.
    """
    import time
    print(f'[always-on] Cartrack polling loop starting '
          f'(interval={interval_seconds}s)', flush=True)
    iteration = 0
    while True:
        iteration += 1
        started = time.time()
        try:
            summary = run_poll()
            elapsed = time.time() - started
            print(f'[#{iteration}] {datetime.utcnow().isoformat()}Z '
                  f'elapsed={elapsed:.1f}s '
                  f'tracked={summary.get("plates_tracked", 0)} '
                  f'toll(in/out)={summary.get("enters_detected", 0)}/{summary.get("exits_detected", 0)} '
                  f'filled={summary.get("toll_fees_filled", 0)} '
                  f'site(in/out)={summary.get("site_visits_opened", 0)}/{summary.get("site_visits_closed", 0)} '
                  f'cycle(start/end)={summary.get("cycles_opened", 0)}/{summary.get("cycles_closed", 0)} '
                  f'errors={len(summary.get("errors", []))}',
                  flush=True)
            if summary.get('errors'):
                for err in summary['errors'][:2]:
                    print(f'  ERR: {err}', flush=True)
        except KeyboardInterrupt:
            print('[always-on] interrupt received — exiting cleanly', flush=True)
            return
        except Exception as e:
            import traceback
            elapsed = time.time() - started
            print(f'[#{iteration}] EXCEPTION after {elapsed:.1f}s: {e}', flush=True)
            traceback.print_exc()
            # Continue anyway — never let a single poll failure stop the loop.

        sleep_for = max(1.0, interval_seconds - (time.time() - started))
        time.sleep(sleep_for)


if __name__ == '__main__':
    # `python cartrack_poll.py`              -> one-shot poll, then exits
    # `python cartrack_poll.py --loop`       -> infinite loop, default 60s
    # `python cartrack_poll.py --loop 30`    -> infinite loop, every 30s
    if len(sys.argv) > 1 and sys.argv[1] == '--loop':
        try:
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        except (ValueError, IndexError):
            interval = 60
        _run_loop(interval_seconds=interval)
    else:
        summary = run_poll()
        print(json.dumps(summary, indent=2, default=str))
        if summary.get('errors'):
            sys.exit(1)
