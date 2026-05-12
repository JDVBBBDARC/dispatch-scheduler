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


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

# How long a trip can be idle before we consider it "closed" and compute toll
TRIP_IDLE_CLOSE_MINUTES = 30

# How many days of CartrackEvent log to keep
EVENT_RETENTION_DAYS = 60

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
        'enters_detected': 0,
        'exits_detected':  0,
        'trips_closed':    0,
        'toll_fees_filled': 0,
        'errors':         [],
    }

    with app.app_context():
        from models_v2 import (db, Plate, TripRecord, Wave, CartrackTruckState,
                                CartrackEvent)
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

    return summary


# ─────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    summary = run_poll()
    print(json.dumps(summary, indent=2, default=str))
    if summary.get('errors'):
        sys.exit(1)
