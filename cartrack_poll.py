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

# Naive-UTC helper used in place of datetime.utcnow() (deprecated in
# Python 3.12+). Defined in models_v2 so all modules share one source
# of truth for the storage convention.
from models_v2 import utc_now

# Make the module importable both standalone and from within the Flask app
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _bootstrap_env_from_wsgi():
    """Populate os.environ from two possible sources, in priority order:

      1. A `.env` file at the project root (KEY=VALUE format, one per line).
         Lines starting with `#` are comments; blank lines are ignored.
         Values can be optionally wrapped in single or double quotes.
         This is the preferred mechanism — works on PA, locally, and in
         any CI/dev environment.

      2. The PythonAnywhere WSGI config file at
         /var/www/<username>_pythonanywhere_com_wsgi.py.
         Specifically, we parse `os.environ['KEY'] = 'VALUE'` lines.
         Useful as a fallback when env vars are already wired into the
         web app and we don't want to duplicate them in a .env file.

    Already-set process env vars are NEVER overwritten — values from .env
    or WSGI only fill in missing keys. This makes the bootstrap safe to
    call from any context (Flask app, always-on task, bash console).
    """
    # ── Source 1: .env file at project root ─────────────────────────
    try:
        env_path = os.path.join(_HERE, '.env')
        if os.path.exists(env_path):
            with open(env_path, encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#') or '=' not in s:
                        continue
                    key, _, val = s.partition('=')
                    key = key.strip()
                    val = val.strip()
                    # Strip surrounding quotes if present.
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                        val = val[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass   # never let .env parsing kill the task

    # ── Source 2: PythonAnywhere WSGI file ──────────────────────────
    try:
        import glob
        candidates = glob.glob('/var/www/*_pythonanywhere_com_wsgi.py')
        if not candidates:
            return
        with open(candidates[0]) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('os.environ[') and '=' in stripped:
                    try:
                        # Execute the assignment in an isolated namespace
                        # to keep the bootstrap surface small and safe.
                        exec(stripped, {'os': os})
                    except Exception:
                        pass
    except Exception:
        pass


# Run env bootstrap at module import time so it's ready before any
# CartrackClient.from_env() call.
_bootstrap_env_from_wsgi()


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

# How long a trip can be idle (no toll geofence event) before we close
# it and compute the GPS-detected toll. Raised 30 -> 45 (June 2026):
# at 30 minutes, a truck stuck in genuinely heavy traffic BETWEEN two
# plazas had its trip closed early as a single-plaza touch, and the
# real transit was never counted (undercount on the Dashboard KPI).
# 45 gives EDSA-grade congestion room to clear while still closing
# trips promptly. Env-overridable so it can be tuned from the
# PythonAnywhere Web tab during monitoring without a code deploy.
TRIP_IDLE_CLOSE_MINUTES = int(os.environ.get('TRIP_IDLE_CLOSE_MINUTES', '45'))

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
#
# EXCEPTION: toll-plaza geofences (category='toll') are EXEMPT from this
# filter. Toll transits are expected to be 30-90 seconds — flagging them
# as drive-by would drop them from the auto-fill logic and break the
# whole point of having toll geofences in Cartrack. See _close_visit().
MIN_VISIT_MINUTES = 5

# Stop-detection threshold for AD-HOC stops (away from any geofence).
# A truck that stops moving (speed <= STOP_SPEED_KMH) for >= this many
# minutes — and is NOT inside any known geofence at the time — gets
# logged as a SiteVisit with geofence_id=NULL, address=reverse-geocode.
# Captures real delivery stops at unmapped locations (e.g., small
# customers, side roads, weigh stations). Configurable via AppSetting
# 'TCT_STOP_DETECTION_MINUTES' — admins can change without code edits.
STOP_DETECTION_MINUTES = 10

# Speed threshold (km/h) for considering a truck "stopped". Cartrack's
# speed field is GPS-derived and tends to spike up to 3-5 km/h on
# stationary trucks due to multi-path error, so we use 5 as the cutoff.
STOP_SPEED_KMH = 5


def _get_runtime_settings(app=None):
    """Read tunable thresholds from AppSetting (DB-backed). Falls back
    to module-level defaults if the setting is missing or unparseable.

    Called once per poll iteration so admin updates take effect on the
    next poll without restarting the worker. Returns a dict.
    """
    if app is None:
        import app_v3 as _app_module
        app = _app_module.app
    with app.app_context():
        from models_v2 import AppSetting
        def _get_int(key, default):
            v = AppSetting.get(key, '')
            try:
                return max(1, int(v)) if v else default
            except (TypeError, ValueError):
                return default
        return {
            'min_visit_minutes':      _get_int('TCT_MIN_VISIT_MINUTES',
                                                MIN_VISIT_MINUTES),
            'stop_detection_minutes': _get_int('TCT_STOP_DETECTION_MINUTES',
                                                STOP_DETECTION_MINUTES),
        }


# Toll-category geofences whose touches must be IGNORED by toll
# detection (no entry/exit state, no CartrackEvent, no trip split).
# Names are compared via _normalize_for_match on the RAW geofence name.
#
# 'toll - clark': legacy pre-split fence that overlaps the SCTEX
# mainline near Clark. Trucks running Pulilan<->Porac drive THROUGH it
# without using any Clark booth, which split one real trip into two
# fragments (Pulilan->Clark + Clark->Porac). The booth-accurate
# "Toll - Clark North"/"Toll - Clark South" fences still detect real
# Clark exits. Ignoring it here beats deleting it in Cartrack Fleet Web
# only in that it needs no manual Cartrack step — remove the entry if
# the fence is ever deleted upstream.
_IGNORED_TOLL_GEOFENCES = {
    'toll - clark',
}


def _strip_toll_prefix(geofence_name):
    """Convert a Cartrack toll geofence name to a cleaned plaza name
    suitable for matching against the toll_rates.json fee matrix.

    Returns '' for geofences listed in _IGNORED_TOLL_GEOFENCES — every
    caller (live enter/exit paths and the backfill) guards with
    `if plaza_name:`, so an empty string cleanly skips toll handling
    for that fence everywhere.

    Two-step strategy:
      1. Light surface cleanup — strip "Toll - " prefix, drop direction
         tags (1, NB, SB, (Entry), etc.), normalise Sta/Sto punctuation.
      2. Aggressive resolution via _resolve_plaza — exact match first,
         then accent/punctuation/case-insensitive match, then fuzzy
         (SequenceMatcher) match with a high threshold.

    Returns the CANONICAL fee-matrix key when a resolution succeeds, so
    downstream compute_toll_fee() lookups always succeed. Returns the
    cleaned (but unresolved) name as a fallback when nothing matches —
    in that case, the polling worker still logs the event but the toll
    fee won't auto-fill until the geofence is renamed.

    Examples:
        "Toll - Mexico"           -> "Mexico"             (exact)
        "Toll - Meycauayan 2"     -> "Meycauayan"         (direction strip + exact)
        "Toll - Sta Rita 1"       -> "Sta. Rita"          (Sta normalisation + exact)
        "Toll - Parañaque"        -> "Parañaque"          (exact)
        "Toll - PARANAQUE"        -> "Parañaque"          (accent-insensitive)
        "Toll - Sto Tomas"        -> "Sto. Tomas"         (Sto normalisation)
        "Toll - san fernndo"      -> "San Fernando"       (fuzzy, typo tolerant)
        "Toll - C-5 Road"         -> "C-5"                (fuzzy)
    """
    if _normalize_for_match(geofence_name) in _IGNORED_TOLL_GEOFENCES:
        return ''

    # First pass — keep direction words and booth numbers intact, then try
    # a HIGH-confidence resolve. This lets multi-word canonical names like
    # "Clark North" / "Clark South" match BEFORE the direction-strip below
    # would collapse them both to a bare "Clark" (which isn't a matrix key).
    base = _strip_prefix_suffix(geofence_name)
    if not base:
        return ''
    canonical, conf = _resolve_plaza(base)
    if canonical and conf >= 0.95:        # exact / normalised / alias only
        return canonical

    # Second pass — also drop direction tags + booth numbers, e.g.
    # "Meycauayan 2" -> "Meycauayan", "Dau 1" -> "Dau".
    cleaned = _clean_plaza_name(geofence_name)
    if not cleaned:
        return ''
    canonical, _conf = _resolve_plaza(cleaned)
    return canonical if canonical else cleaned


def _strip_prefix_suffix(geofence_name):
    """Strip the 'Toll -' prefix, ' Plaza'/' Toll' suffix, and normalise
    Sta/Sto punctuation — but KEEP direction words ('North') and booth
    numbers ('2') so a first-pass exact match can use them."""
    import re
    if not geofence_name:
        return ''
    s = geofence_name.strip()
    upper = s.upper()

    # Prefix strip — try the most specific patterns first.
    if upper.startswith('TOLL -') or upper.startswith('TOLL- '):
        s = s.split('-', 1)[1].strip()
    else:
        for prefix in ('TOLLBOOTH ', 'TOLL PLAZA ', 'TOLL '):
            if upper.startswith(prefix):
                s = s[len(prefix):].strip()
                break

    # Suffix strip — always check, even if a prefix was already stripped
    # ("Toll - Tabang Plaza" -> "Tabang Plaza" -> "Tabang").
    upper2 = s.upper()
    for suffix in (' TOLL PLAZA', ' TOLL', ' PLAZA'):
        if upper2.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break

    # Sta/Sto canonical form (fee matrix uses periods)
    s = re.sub(r'\bSta\b(?!\.)', 'Sta.', s)
    s = re.sub(r'\bSto\b(?!\.)', 'Sto.', s)
    return s.strip()


def _clean_plaza_name(geofence_name):
    """_strip_prefix_suffix + drop direction tags / booth numbers. Returns
    a normalised string ready to be passed into _resolve_plaza for the
    actual matching."""
    import re
    s = _strip_prefix_suffix(geofence_name)
    if not s:
        return ''

    # Direction tag strip
    s = re.sub(r'\s+\d+$', '', s)
    s = re.sub(r'\s+(NB|SB|EB|WB|NORTH|SOUTH|EAST|WEST|N|S|E|W)$',
                '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*\((NB|SB|EB|WB|NORTH|SOUTH|EAST|WEST|ENTRY|EXIT)\)$',
                '', s, flags=re.IGNORECASE)
    return s.strip()


def _normalize_for_match(name):
    """Aggressive normalisation for fuzzy comparison: lowercase, strip
    accents, drop punctuation. Used only for matching — NOT for display
    or storage."""
    import re
    import unicodedata
    if not name:
        return ''
    s = name.strip().lower()
    # Strip accents: Parañaque -> Paranaque, España -> Espana
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')
    # Strip everything that isn't a letter, digit, space, hyphen, or slash
    s = re.sub(r'[^a-z0-9\s\-/]', '', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# Cached fee matrix — compute_toll_fee() used to re-open and re-parse
# toll_rates.json on EVERY call (once per closed trip in the worker, once
# per row in the recompute script). Cache it keyed on the file's mtime so
# a rate update on disk is still picked up without restarting the
# long-running worker.
_TOLL_RATES_CACHE = None
_TOLL_RATES_MTIME = None


def _load_toll_rates():
    """Return the parsed toll_rates.json, re-reading only when the file
    changes on disk."""
    global _TOLL_RATES_CACHE, _TOLL_RATES_MTIME
    path = os.path.join(_HERE, 'static', 'toll_rates.json')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _TOLL_RATES_CACHE is None or mtime != _TOLL_RATES_MTIME:
        with open(path, encoding='utf-8') as f:
            _TOLL_RATES_CACHE = json.load(f)
        _TOLL_RATES_MTIME = mtime
    return _TOLL_RATES_CACHE


# Cached lookup tables — built lazily from toll_rates.json on first use.
_PLAZA_CANONICAL_KEYS = None
_PLAZA_NORM_TO_CANONICAL = None


def _load_plaza_keys():
    """Build (and cache) the list of canonical plaza names from the fee
    matrix plus a normalised lookup table. Reads the same JSON file as
    compute_toll_fee()."""
    global _PLAZA_CANONICAL_KEYS, _PLAZA_NORM_TO_CANONICAL
    if _PLAZA_CANONICAL_KEYS is not None:
        return _PLAZA_CANONICAL_KEYS, _PLAZA_NORM_TO_CANONICAL
    keys = set()
    try:
        data = _load_toll_rates()
        for exp_key, exp_data in data.items():
            if not isinstance(exp_data, dict):
                continue
            for k, v in exp_data.items():
                if isinstance(k, str) and k.startswith('Class ') and isinstance(v, dict):
                    keys.update(v.keys())
                    # Also include the destination plaza names — they
                    # may not appear as a top-level source.
                    for dest_dict in v.values():
                        if isinstance(dest_dict, dict):
                            keys.update(dest_dict.keys())
    except Exception:
        pass
    _PLAZA_CANONICAL_KEYS = sorted(keys)
    _PLAZA_NORM_TO_CANONICAL = {_normalize_for_match(k): k
                                 for k in _PLAZA_CANONICAL_KEYS}
    return _PLAZA_CANONICAL_KEYS, _PLAZA_NORM_TO_CANONICAL


# ─────────────────────────────────────────────────────────────────────
# Manual geofences (coord-based workaround for hidden Cartrack
# geofences). Loaded from manual_geofences.json — or its legacy alias
# manual_homes.json — at the project root.
#
# Use this when a real Cartrack geofence exists but is hidden from the
# /rest/geofences API (visibility bug). The polling worker pre-creates
# a CartrackGeofence row in the DB for each manual entry, then on each
# poll computes which manual fences the truck is inside via haversine
# and adds their cartrack_id values to current_geofence_uuids.
#
# All downstream logic (cycle tracking, SiteVisit creation, drive-by
# filtering, Plate Status display) treats manual geofences as if they
# came from Cartrack itself — no special-case branches needed.
# ─────────────────────────────────────────────────────────────────────

_MANUAL_GF_CACHE  = None
_MANUAL_GF_MTIME  = None
_MANUAL_GF_SOURCE = None


def _slugify(name):
    """Convert 'San Ildefonso Quarry' -> 'san-ildefonso-quarry' for
    use in the synthetic cartrack_id of a manual geofence row."""
    import re
    s = name.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-') or 'unknown'


def _load_manual_geofences():
    """Load manual geofences from manual_geofences.json (preferred) or
    manual_homes.json (legacy fallback).

    Format (JSON array of objects):
        [
          {
            "name":     "Parking Plant 1",
            "category": "home",           # home | quarry | customer | fuel | ...
            "lat":      14.905736,
            "lng":      120.834852,
            "radius_m": 200
          },
          ...
        ]

    Legacy manual_homes.json entries default to category='home'.

    Cached and re-read on file modification time changes, so admins
    can edit the JSON file live without restarting the polling worker.
    """
    global _MANUAL_GF_CACHE, _MANUAL_GF_MTIME, _MANUAL_GF_SOURCE
    candidates = [
        os.path.join(_HERE, 'manual_geofences.json'),
        os.path.join(_HERE, 'manual_homes.json'),   # legacy
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if path is None:
        _MANUAL_GF_CACHE = []
        _MANUAL_GF_MTIME = None
        _MANUAL_GF_SOURCE = None
        return _MANUAL_GF_CACHE

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None

    if (mtime == _MANUAL_GF_MTIME
            and path == _MANUAL_GF_SOURCE
            and _MANUAL_GF_CACHE is not None):
        return _MANUAL_GF_CACHE

    fences = []
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
        is_legacy = path.endswith('manual_homes.json')
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                try:
                    name = str(entry.get('name', '')).strip()
                    lat  = float(entry['lat'])
                    lng  = float(entry['lng'])
                    radius_m = int(entry.get('radius_m', 200))
                    category = str(entry.get('category', 'home')).strip().lower()
                    if is_legacy:
                        category = 'home'   # back-compat
                    if name and -90 <= lat <= 90 and -180 <= lng <= 180:
                        fences.append({
                            'name':     name,
                            'category': category or 'other',
                            'lat':      lat,
                            'lng':      lng,
                            'radius_m': radius_m,
                            'cartrack_id': f'manual-{_slugify(name)}',
                        })
                except (KeyError, TypeError, ValueError):
                    continue
    except Exception:
        pass

    _MANUAL_GF_CACHE  = fences
    _MANUAL_GF_MTIME  = mtime
    _MANUAL_GF_SOURCE = path
    return fences


# Backward-compatible alias (used by legacy callers).
_load_manual_homes = _load_manual_geofences


def _check_manual_geofences(lat, lng):
    """Return a list of manual-geofence dicts the given GPS is inside.

    A truck can be in multiple manual fences if their radii overlap
    (rare but legal). Caller is responsible for choosing precedence.
    """
    if lat is None or lng is None:
        return []
    inside = []
    for mg in _load_manual_geofences():
        d = haversine_meters(lat, lng, mg['lat'], mg['lng'])
        if d <= mg['radius_m']:
            inside.append(mg)
    return inside


def _check_manual_homes(lat, lng, log=None):
    """Legacy compat — return name of first manual HOME a truck is in,
    or None. Used by older code paths that haven't been migrated yet."""
    for mg in _check_manual_geofences(lat, lng):
        if mg['category'] == 'home':
            return mg['name']
    return None


def _sync_manual_geofences_to_db(app=None):
    """Ensure each entry in manual_geofences.json has a corresponding
    CartrackGeofence row in the database, using a synthetic cartrack_id
    (e.g., 'manual-san-ildefonso-quarry'). Idempotent — safe to call
    on every poll.

    Returns a dict mapping cartrack_id -> CartrackGeofence row id, used
    by the polling worker to add manual-fence UUIDs to the truck's
    current_geofence_uuids set.
    """
    if app is None:
        import app_v3 as _app_module
        app = _app_module.app
    out = {}
    fences = _load_manual_geofences()
    if not fences:
        return out
    with app.app_context():
        from models_v2 import db, CartrackGeofence
        from datetime import datetime as _dt
        for mg in fences:
            row = (CartrackGeofence.query
                   .filter_by(cartrack_id=mg['cartrack_id'])
                   .first())
            if row is None:
                row = CartrackGeofence(
                    cartrack_id          = mg['cartrack_id'],
                    name                 = mg['name'],
                    description          = 'Manual entry (coord-based, '
                                            'bypasses Cartrack API visibility)',
                    position_description = '',
                    colour               = '',
                    polygon_wkt          = '',
                    category             = mg['category'],
                    is_home              = (mg['category'] == 'home'),
                    last_synced_at       = _dt.utcnow(),
                )
                db.session.add(row)
            else:
                # Keep DB in sync with JSON edits (name/category/etc.)
                changed = False
                if row.name != mg['name']:
                    row.name = mg['name']; changed = True
                if row.category != mg['category']:
                    row.category = mg['category']; changed = True
                new_home = (mg['category'] == 'home')
                if row.is_home != new_home:
                    row.is_home = new_home; changed = True
                if changed:
                    row.last_synced_at = _dt.utcnow()
            db.session.flush()
            out[mg['cartrack_id']] = row.id
        db.session.commit()
    return out


# Geofence/booth names whose canonical fee-matrix key isn't reachable by
# cleanup + fuzzy alone (the town/exit is named differently from the
# plaza). Keys are in _normalize_for_match() form; values must be exact
# fee-matrix keys. Mirrors the build-time aliases in
# integration_doc/build_toll_geofences.py.
_PLAZA_ALIASES = {
    'florida':  'Floridablanca',   # NLEX exit named after the town
    'mabiga':   'Mabalacat',       # Mabalacat plaza sits in Brgy. Mabiga
    # Fallback for a legacy bare "Clark" geofence (pre-split). The fee
    # matrix has no plain "Clark" — only Clark South / Clark North — and
    # fuzzy match scores too low (~0.63) to pick either, so an unsplit
    # "Clark" crossing would otherwise log with NO fee. We bill it as
    # Clark South (the main SCTEX Clark interchange exit). PROPER FIX:
    # replace the single "Clark" geofence in Cartrack with the two
    # booth-accurate ones already in toll_geofences.json.
    'clark':    'Clark South',
}


def _resolve_plaza(cleaned_name, threshold=0.85):
    """Resolve a cleaned plaza name to its canonical fee-matrix key.

    Tiered matching:
        1. Exact case-sensitive match           (confidence = 1.0)
        2. Normalised match (accents/case/etc.) (confidence = 0.95)
        2.5 Explicit alias (Florida->Floridablanca) (confidence = 0.95)
        3. Fuzzy SequenceMatcher ratio          (confidence = ratio)

    Returns (canonical_key, confidence) on success. Returns (None, 0.0)
    if even the best fuzzy match falls below `threshold`.
    """
    if not cleaned_name:
        return None, 0.0
    canonical_keys, norm_to_canonical = _load_plaza_keys()
    if not canonical_keys:
        return None, 0.0

    # Tier 1 — exact
    if cleaned_name in canonical_keys:
        return cleaned_name, 1.0

    # Tier 2 — normalised exact
    norm_target = _normalize_for_match(cleaned_name)
    if norm_target in norm_to_canonical:
        return norm_to_canonical[norm_target], 0.95

    # Tier 2.5 — explicit alias (only if the target key really exists)
    alias = _PLAZA_ALIASES.get(norm_target)
    if alias and alias in canonical_keys:
        return alias, 0.95

    # Tier 3 — fuzzy match against the normalised key set
    from difflib import SequenceMatcher
    best_key, best_ratio = None, 0.0
    for norm_key, canon in norm_to_canonical.items():
        r = SequenceMatcher(None, norm_target, norm_key).ratio()
        if r > best_ratio:
            best_key, best_ratio = canon, r
    if best_ratio >= threshold:
        return best_key, best_ratio
    return None, 0.0

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
    """Return list of {plaza, expressway, [lat], [lng], [radius_m]}.

    Historically this loaded GPS coordinates from the `coordinates` block
    in static/toll_rates.json, used by the coordinate-based plaza
    detection. That detection has been retired in favour of Cartrack-side
    geofences; the coordinates block was removed from the JSON in May 2026.

    The function is retained because the Cartrack-side toll detection
    still needs the plaza→expressway mapping (for labelling each
    CartrackEvent with which expressway the plaza belongs to). The
    mapping is now derived from the fee matrix structure: every plaza
    that appears as a source in a `Class N` block is associated with
    that block's expressway.

    If the `coordinates` block is still present (legacy), its lat/lng/
    radius_m fields are included for backward compatibility.
    """
    path = os.path.join(_HERE, 'static', 'toll_rates.json')
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    plazas = []
    seen = set()
    for exp_key, exp_data in data.items():
        if not isinstance(exp_data, dict):
            continue

        # Legacy: pick up coordinates if the block is still in the JSON.
        coords = exp_data.get('coordinates') or {}
        for plaza, c in coords.items():
            key = (exp_key, plaza)
            if key in seen:
                continue
            seen.add(key)
            plazas.append({
                'plaza':      plaza,
                'expressway': exp_key,
                'lat':        c.get('lat'),
                'lng':        c.get('lng'),
                'radius_m':   c.get('radius_m', 200),
            })

        # Primary: derive plaza names from the fee matrix. Every source
        # plaza in any Class N block belongs to this expressway.
        for k, v in exp_data.items():
            if not (isinstance(k, str) and k.startswith('Class ')
                    and isinstance(v, dict)):
                continue
            for plaza in v.keys():
                key = (exp_key, plaza)
                if key in seen:
                    continue
                seen.add(key)
                plazas.append({
                    'plaza':      plaza,
                    'expressway': exp_key,
                })

    return plazas


def find_plazas_at_position(lat, lng, plazas):
    """DEPRECATED: coordinate-based toll plaza detection.

    Retained only for backward compatibility with any external callers /
    debugging utilities. The polling worker no longer uses this — toll
    plaza detection is now done entirely via Cartrack-side geofences
    (category='toll') as of May 2026. The `coordinates` block was
    stripped from static/toll_rates.json at the same time, so this
    function returns an empty list for plazas that have no lat/lng.

    Will be removed in a future release.
    """
    if lat is None or lng is None:
        return []
    inside = []
    for p in plazas:
        if p.get('lat') is None or p.get('lng') is None:
            continue   # plaza has no coordinates (post-strip)
        if haversine_meters(lat, lng, p['lat'], p['lng']) <= p.get('radius_m', 200):
            inside.append(p)
    return inside


# ─────────────────────────────────────────────────────────────────────
# Toll fee computation — reuses the existing BFS routing
# ─────────────────────────────────────────────────────────────────────

def compute_toll_fee(entry_plaza, exit_plaza, toll_class='Class 3'):
    """Compute toll fee for entry -> exit. Returns (fee, expressway_key) or (None, None)."""
    data = _load_toll_rates()

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
        cost, segs = find_toll_route(entry_plaza, exit_plaza, toll_class, data)
        if cost is not None:
            # Label with the actual expressways traversed ("NLEX_SCTEX +
            # NLEX_Connector") instead of an opaque "multi" — dedup while
            # keeping route order; zero-cost connector hops (same-station
            # transfers) carry no fee but still name their expressway.
            chain = []
            for s in (segs or []):
                e = s.get('expressway')
                if e and e not in chain:
                    chain.append(e)
            label = ' + '.join(chain) if chain else 'multi'
            return float(cost), label
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
    # Home base — special case, the only category that sets is_home=True.
    # Multiple homes are supported: a truck returning to ANY home closes
    # its open cycle, and leaving ANY home opens a new cycle. Add more
    # entries here as the fleet grows.
    ('home', [
        'BIG BEN SCM',
        'PLANT 1',     # 2nd home — Big Ben Plant 1 dispatch yard
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
        now = utc_now()

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

                # Promote-only home re-check: even if the name didn't
                # change, if the home-pattern list now matches this
                # geofence (e.g., we added 'PLANT 1' to the patterns in
                # a code release), mark it home so cycle tracking picks
                # it up on the next poll. We only PROMOTE — never demote
                # — so any manual is_home edits in the DB are preserved.
                _, should_be_home = _categorize_geofence(name)
                if should_be_home and not existing.is_home:
                    existing.category = 'home'
                    existing.is_home  = True
                    summary['recategorized'] += 1
                    log.info('[sync] PROMOTE %s -> home', name)

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

    # Re-read tunable thresholds from AppSetting on every poll so admin
    # edits via the Truck Cycle Time settings modal take effect within
    # one minute, no worker restart needed.
    settings = _get_runtime_settings(app=app)
    rt_min_visit_minutes      = settings['min_visit_minutes']
    rt_stop_detection_minutes = settings['stop_detection_minutes']

    summary = {
        'polled_at':      utc_now().isoformat() + 'Z',
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

        # ── 4. Load plaza coordinates + sync manual geofences once ───
        plazas = load_plaza_coords()
        # Ensure CartrackGeofence rows exist for every manual entry,
        # so the visit-creation logic downstream can link via id.
        _sync_manual_geofences_to_db(app=app)
        now = utc_now()

        # ── 5. For each mapped plate, diff state and emit events ─────
        for plate in mapped_plates:
            status = by_vid.get(plate.cartrack_vehicle_id)
            if not status:
                continue  # no recent position for this truck

            loc = status.get('location') or {}
            lat = loc.get('latitude')
            lng = loc.get('longitude')

            # Load or create state row
            state = CartrackTruckState.query.filter_by(plate_id=plate.id).first()
            if state is None:
                state = CartrackTruckState(plate_id=plate.id, current_plazas='')
                db.session.add(state)
                db.session.flush()

            summary['plates_tracked'] += 1

            # Update last position + live status fields (always, every poll).
            # Powers the live "where is this truck and what's it doing" cards
            # on /truck-cycle-time without re-hitting Cartrack on page load.
            if lat is not None and lng is not None:
                state.last_lat = lat
                state.last_lng = lng
                state.last_position_at = now
            state.last_position_description = (loc.get('position_description') or '')[:295]
            state.last_idling   = bool(status.get('idling', False))
            state.last_ignition = bool(status.get('ignition', False))
            try:
                state.last_speed = int(status.get('speed') or 0)
            except (TypeError, ValueError):
                state.last_speed = 0
            # Snapshot which Cartrack geofences the truck is currently in,
            # so the API can show "Currently at: AHNEX" without re-querying.
            state.last_geofence_uuids = ','.join(sorted(loc.get('geofence_ids') or []))

            # NOTE: Coordinate-based toll plaza detection has been REMOVED.
            #
            # Previously this section ran find_plazas_at_position() against
            # the haversine distances stored in static/toll_rates.json. The
            # approach was unreliable in practice — trucks at highway speed
            # traverse a 200-500m plaza zone in seconds, well under the
            # 60-second polling cadence, so most transits were missed. It
            # also produced false positives where plaza coordinates
            # overlapped with nearby parking, gas stations, or the BIG BEN
            # SCM yard.
            #
            # All toll-plaza detection now comes from Cartrack-side
            # geofences (categorised by name match in _categorize_geofence).
            # The visit-OPEN block below writes CartrackEvent rows and
            # updates state.entry_plaza / state.last_plaza whenever a
            # truck enters a 'toll' geofence — the same downstream
            # idle-close + compute_toll_fee path then auto-fills the trip.
            #
            # The fee matrix in toll_rates.json is still used by
            # compute_toll_fee(); only the coordinate-based detection
            # is removed.

            # Clear any stale coord-based plaza state from previous polls.
            if state.current_plazas:
                state.current_plazas = ''

            # ── 5b. CARTRACK-SIDE GEOFENCE TRACKING (sites + cycles) ──
            # Cartrack reports geofence_ids per truck in get_status, so we
            # don't recompute geometry — just diff vs. the open SiteVisits
            # we have for this plate.

            current_geofence_uuids = set(loc.get('geofence_ids') or [])

            # ── Merge manual geofences via haversine ──────────────────
            # Manual entries (manual_geofences.json) bypass the Cartrack
            # /rest/geofences visibility issue. Their cartrack_ids look
            # like 'manual-<slug>' and have corresponding DB rows that
            # _sync_manual_geofences_to_db() created above. Adding them
            # to current_geofence_uuids lets the rest of the polling
            # logic treat them identically to real Cartrack geofences:
            # cycle home detection (if category=home), SiteVisit
            # creation (if not), drive-by filtering, etc.
            for mg in _check_manual_geofences(lat, lng):
                current_geofence_uuids.add(mg['cartrack_id'])
            current_geofences = []
            if current_geofence_uuids:
                current_geofences = (CartrackGeofence.query
                                      .filter(CartrackGeofence.cartrack_id.in_(current_geofence_uuids))
                                      .all())
            current_gf_local_ids = {g.id for g in current_geofences}

            # Previously inside = plate has open (unclosed) SiteVisits
            open_visits = (SiteVisit.query
                            .filter(SiteVisit.plate_id == plate.id,
                                    SiteVisit.exit_at.is_(None))
                            .all())
            previous_gf_local_ids = {v.geofence_id for v in open_visits}

            gf_new_enters = current_gf_local_ids - previous_gf_local_ids
            gf_new_exits  = previous_gf_local_ids - current_gf_local_ids
            gf_still_in   = current_gf_local_ids & previous_gf_local_ids

            # Build gf_by_id from BOTH currently-inside geofences AND any
            # geofences referenced by open visits (i.e., geofences the
            # truck may have just exited). Without the exit-side lookup,
            # the close-visit loop below sees gf=None for every exit, which
            # incorrectly flags toll transits as drive-by AND silently
            # skips the symmetric CartrackEvent EXIT row. That's why the
            # Toll Log shows only ENTER rows for trucks that have clearly
            # transited multiple plazas.
            gf_by_id = {g.id: g for g in current_geofences}
            exit_gf_ids = previous_gf_local_ids - set(gf_by_id.keys())
            # Filter out None (ad-hoc stop SiteVisits have geofence_id=NULL).
            exit_gf_ids.discard(None)
            if exit_gf_ids:
                for g in (CartrackGeofence.query
                           .filter(CartrackGeofence.id.in_(exit_gf_ids))
                           .all()):
                    gf_by_id[g.id] = g

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
            #
            # Multi-home support: ANY home geofence opens/closes the
            # cycle. Trucks moving between two homes (e.g., BIG BEN SCM
            # -> Plant 1) will get a short cycle for that transit, which
            # is the desired behavior — both are operational dispatch
            # points and the trip between them is a real journey.
            home_gfs = CartrackGeofence.query.filter_by(is_home=True).all()
            home_cartrack_ids = {h.cartrack_id for h in home_gfs}
            home_db_ids       = {h.id for h in home_gfs}
            # Includes both Cartrack-side AND manual home geofences,
            # since manual homes are pre-merged into current_geofence_uuids
            # earlier in this iteration.
            is_at_home_now    = bool(home_cartrack_ids & current_geofence_uuids)
            was_at_home_prev  = open_cycle is None   # no open cycle ⇒ was at home

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
            # ALL home geofences in the loops below so trucks parked at
            # any depot don't generate phantom 18-hour "visits"
            # cluttering the UI.

            # Open new SiteVisits (skip every home geofence)
            for gf_id in gf_new_enters:
                if gf_id in home_db_ids and not TRACK_HOME_AS_VISIT:
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

                # ── Cartrack-side toll detection ──────────────────────
                # When a truck enters a 'toll' category geofence, feed
                # the canonical plaza name into the same entry/last
                # plaza state that the coord-based detector uses, AND
                # emit a CartrackEvent so the transit appears in the
                # Toll Log UI. The downstream 30-min idle-close logic
                # + compute_toll_fee then handles fee computation
                # without modification.
                #
                # This is a drop-in upgrade for the coord-based path:
                # more reliable, no polling gaps, updates immediately
                # on geofence entry rather than depending on a poll
                # catching the truck mid-zone.
                if gf.category == 'toll':
                    plaza_name = _strip_toll_prefix(gf.name)
                    if plaza_name:
                        if not state.entry_plaza:
                            state.entry_plaza = plaza_name
                        state.last_plaza    = plaza_name
                        state.last_event_ts = now
                        # Best-effort expressway lookup. `plazas` is a flat
                        # list of {plaza, expressway, lat, lng, radius_m}.
                        expressway = None
                        for p in (plazas or []):
                            if p.get('plaza') == plaza_name:
                                expressway = p.get('expressway')
                                break
                        db.session.add(CartrackEvent(
                            plate_id=plate.id, event_type='enter',
                            plaza_name=plaza_name, expressway=expressway,
                            lat=lat, lng=lng,
                        ))
                        summary['enters_detected'] += 1
                        log.info('[TOLL-GEO] %s entered Cartrack plaza %s '
                                 '(entry=%s, last=%s, exp=%s)',
                                 plate.display, plaza_name,
                                 state.entry_plaza, state.last_plaza,
                                 expressway or '?')

            # Close exited SiteVisits (drive-by flagged if too short).
            #
            # ── Outside-poll hysteresis (for non-toll geofences) ─────
            # Cartrack occasionally drops a poll cycle's geofence_ids
            # (signal blip, device sleep, boundary jitter). Without a
            # guard, ANY single missed reading closes the visit and
            # produces a phantom EXIT/ENTER ping-pong on the next poll.
            #
            # For non-toll geofences (customer sites, fuel stations,
            # quarries, etc.) we require OUTSIDE_POLL_THRESHOLD
            # consecutive "outside" polls before actually closing the
            # visit. A single dropped reading no longer triggers a
            # phantom exit — and a real exit just takes one extra
            # polling cycle to register (~60s lag).
            #
            # Toll-plaza geofences (category='toll') BYPASS the
            # hysteresis: real transits are 30-90 seconds, so adding a
            # 60-second guard would miss legitimate exits. Toll exits
            # close immediately, same as before.
            #
            # ── Drive-by filter ──────────────────────────────────────
            # Visits shorter than MIN_VISIT_MINUTES are flagged
            # is_drive_by=True and hidden from the UI by default.
            # Toll plazas are EXEMPT — see above for rationale.
            OUTSIDE_POLL_THRESHOLD = 2   # consecutive outside polls before closing
            min_seconds = rt_min_visit_minutes * 60

            for visit in open_visits:
                gf = gf_by_id.get(visit.geofence_id)
                is_toll_gf = bool(gf and gf.category == 'toll')

                if visit.geofence_id in gf_new_exits:
                    # Cartrack reports the truck is OUTSIDE this geofence
                    # right now. Apply hysteresis unless it's a toll plaza.
                    if not is_toll_gf:
                        visit.outside_poll_count = (visit.outside_poll_count or 0) + 1
                        if visit.outside_poll_count < OUTSIDE_POLL_THRESHOLD:
                            # Not yet enough consecutive outside polls — keep
                            # the visit open and wait. Log lightly so we can
                            # see hysteresis activity if needed.
                            log.info('[HYSTERESIS] %s outside %s for %d/%d polls '
                                     '(keeping visit open)',
                                     plate.display,
                                     gf.name if gf else '?',
                                     visit.outside_poll_count,
                                     OUTSIDE_POLL_THRESHOLD)
                            continue
                    # Threshold met (or it's a toll plaza) — close the visit.
                    visit.exit_at = now
                    duration = max(0, int((now - visit.enter_at).total_seconds()))
                    visit.duration_seconds = duration
                    if duration > 0:
                        visit.idling_pct = round(
                            100.0 * (visit.idling_seconds or 0) / duration, 1)
                    visit.is_drive_by = (not is_toll_gf) and (duration < min_seconds)
                    summary['site_visits_closed'] += 1
                    if visit.is_drive_by:
                        log.info('[VISIT-OUT] drive-by (%ds < %dmin threshold) %s',
                                 duration, rt_min_visit_minutes, plate.display)
                    elif is_toll_gf and duration < min_seconds:
                        log.info('[VISIT-OUT] toll plaza %s (%ds — drive-by exempt) %s',
                                 gf.name if gf else '?', duration, plate.display)

                    # For toll geofences, also emit a CartrackEvent EXIT
                    # so the transit appears symmetrically in the Toll Log.
                    if is_toll_gf:
                        plaza_name = _strip_toll_prefix(gf.name)
                        if plaza_name:
                            state.last_event_ts = now
                            db.session.add(CartrackEvent(
                                plate_id=plate.id, event_type='exit',
                                plaza_name=plaza_name, expressway=None,
                                lat=lat, lng=lng,
                            ))
                            summary['exits_detected'] += 1
                            log.info('[TOLL-GEO] %s exited Cartrack plaza %s '
                                     '(duration=%ds)', plate.display,
                                     plaza_name, duration)
                elif visit.geofence_id in gf_still_in:
                    # Truck is still inside this geofence — reset any
                    # accumulated outside-poll count. A single blip
                    # during a long stay no longer leaves a stale count
                    # that could prematurely close the visit later.
                    if visit.outside_poll_count:
                        visit.outside_poll_count = 0

            # Accumulate idling time for currently-inside visits
            if is_idling and gf_still_in:
                for visit in open_visits:
                    if visit.geofence_id in gf_still_in:
                        visit.idling_seconds = (visit.idling_seconds or 0) + POLL_INTERVAL_SECONDS
                        summary['idle_seconds_logged'] += POLL_INTERVAL_SECONDS

            # ── 5b.4 AD-HOC STOP DETECTION ──────────────────────────
            # Captures stops outside any known geofence (e.g., side
            # roads, small customers, weigh stations not in Cartrack).
            # State machine on CartrackTruckState:
            #   - Truck stopped + not in any geofence  -> start tracking
            #   - Truck resumed moving + tracking      -> close visit
            #                                            (only if dwell
            #                                             >= stop_min)
            stop_min_seconds = rt_stop_detection_minutes * 60
            speed = state.last_speed or 0
            is_stopped_now = speed <= STOP_SPEED_KMH
            inside_any_known_gf = bool(current_geofence_uuids)

            if state.last_stop_started_at is None:
                # No active stop tracking. Start one if conditions match.
                if is_stopped_now and not inside_any_known_gf and (lat is not None and lng is not None):
                    state.last_stop_started_at = now
                    state.last_stop_lat        = lat
                    state.last_stop_lng        = lng
                    state.last_stop_address    = (
                        state.last_position_description or '')[:295]
            else:
                # Active stop in progress.
                if is_stopped_now and not inside_any_known_gf:
                    # Still stopped + outside any geofence — keep accumulating
                    # (do nothing; duration computed on close).
                    pass
                else:
                    # Truck moved OR entered a known geofence — close the
                    # ad-hoc stop. Only log it if dwell >= threshold.
                    started_at = state.last_stop_started_at
                    stop_duration = int((now - started_at).total_seconds())
                    if stop_duration >= stop_min_seconds:
                        sv = SiteVisit(
                            plate_id   = plate.id,
                            geofence_id = None,
                            enter_at   = started_at,
                            exit_at    = now,
                            duration_seconds = stop_duration,
                            idling_seconds   = 0,
                            idling_pct       = None,
                            is_drive_by      = False,
                            lat              = state.last_stop_lat,
                            lng              = state.last_stop_lng,
                            address          = (state.last_stop_address or '')[:295],
                            cycle_id         = open_cycle.id if open_cycle else None,
                        )
                        db.session.add(sv)
                        summary.setdefault('ad_hoc_stops_logged', 0)
                        summary['ad_hoc_stops_logged'] += 1
                        log.info('[STOP] %s: %dmin at %s',
                                 plate.display,
                                 stop_duration // 60,
                                 (state.last_stop_address or '(unknown)')[:60])
                    # Clear tracking either way (don't log <threshold stops)
                    state.last_stop_started_at = None
                    state.last_stop_lat        = None
                    state.last_stop_lng        = None
                    state.last_stop_address    = None

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

            # Compute toll fee from the matrix. We DO NOT write this to
            # TripRecord.toll_fee — that field is reserved for manual
            # encoding by dispatchers based on physical receipts /
            # RFID statements. The GPS-detected fee is logged as a
            # CartrackEvent only, which surfaces in the Toll Log page
            # and aggregates into a separate Dashboard KPI.
            #
            # This separation lets Finance compare GPS-detected tolls
            # (what the matrix predicts) against manual entries (what
            # the receipts actually show) — useful for catching toll
            # exemptions, RFID glitches, or missed transits.
            #
            # toll_class is read from the Plate row — heavy trucks
            # default to Class 3, but vans (L300) are Class 1 and
            # light trucks (MDT) are Class 2. Without this lookup,
            # vans would be overcharged ~3x the actual fee.
            plate_toll_class = (state.plate.toll_class
                                if state.plate and state.plate.toll_class
                                else 'Class 3')
            fee, expressway = compute_toll_fee(entry, exit_plaza,
                                                plate_toll_class)

            # Log the trip_closed event with the computed fee. No
            # TripRecord lookup needed — Schedule entries are owned by
            # the dispatcher, not the polling worker.
            db.session.add(CartrackEvent(
                plate_id=state.plate_id, event_type='trip_closed',
                plaza_name=None, expressway=expressway,
                trip_id=None,                # decoupled — no trip match
                toll_fee=fee, toll_entry=entry, toll_exit=exit_plaza,
                notes=('no rate found' if fee is None else 'gps-detected'),
            ))
            if fee is not None:
                summary['toll_fees_filled'] += 1
                log.info('[TOLL-GPS] %s: %s -> %s = PHP %s (%s, %s) — Dashboard KPI only',
                         state.plate.display if state.plate else state.plate_id,
                         entry, exit_plaza, fee, expressway or '?', plate_toll_class)
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

# How often to piggyback the JobOrders/ERP sync onto Cartrack polling.
# At the default 60s polling interval, JOBORDERS_SYNC_EVERY_N=10 means
# the JobOrders sync fires every 10 minutes — frequent enough that new
# repair requests show up promptly on the /breakdown page, but rare
# enough that we don't hammer the ERP API. Tune via the
# JOBORDERS_SYNC_EVERY_N env var if you need a different cadence.
JOBORDERS_SYNC_EVERY_N = int(os.environ.get('JOBORDERS_SYNC_EVERY_N', '10'))

# How often to backfill missed toll events from Cartrack's server-side
# event log (cartrack_trips_backfill). At highway speed a truck transits
# a toll geofence in 7-14 seconds; our 60s polling has roughly a 1-in-5
# chance of catching the truck mid-transit, so ~80% of brief transits
# slip between polls. This backfill closes the gap by reading
# /rest/vehicles/events, which records every transit server-side. Runs
# every TOLL_BACKFILL_EVERY_N iterations (default 30 = ~30 min) so the
# lookback window stays small and the API response compact.
TOLL_BACKFILL_EVERY_N = int(os.environ.get('TOLL_BACKFILL_EVERY_N', '30'))


def _run_loop(interval_seconds=60):
    """Run run_poll() forever, sleeping between iterations.

    Intended for PythonAnywhere Always-On Tasks: PA keeps the process
    alive and restarts it on hard crash, so we just need a loop that
    polls, logs a compact one-line summary, and sleeps.

    Transient exceptions (Cartrack API hiccup, DB blip) are caught so
    they don't take the loop down — only KeyboardInterrupt exits.

    JobOrders piggyback: every Nth iteration we also call
    joborders_sync.run_sync(). Sharing the always-on task slot keeps
    PA's task count down (we only need one) and lines up the two
    integrations on the same heartbeat — easier to reason about
    overall sync behaviour from a single log stream.
    """
    import time
    print(f'[always-on] Cartrack polling loop starting '
          f'(interval={interval_seconds}s, '
          f'joborders sync every {JOBORDERS_SYNC_EVERY_N} iterations)',
          flush=True)
    iteration = 0
    while True:
        iteration += 1
        started = time.time()
        try:
            summary = run_poll()
            elapsed = time.time() - started
            print(f'[#{iteration}] {utc_now().isoformat()}Z '
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

        # ── Toll backfill piggyback ────────────────────────────────
        # Run after the live poll. Pulls Cartrack's server-side event
        # log for any toll transits the live poll missed in the last
        # ~35 minutes, dedupes against existing CartrackEvent rows,
        # inserts only the gaps. Heavily wrapped in try/except — a
        # failure here must NOT take down the live polling loop.
        if iteration % TOLL_BACKFILL_EVERY_N == 0:
            bf_started = time.time()
            try:
                from cartrack_trips_backfill import backfill_toll_events
                bf_summary = backfill_toll_events(app=None)
                bf_elapsed = time.time() - bf_started
                print(f'  [BACKFILL #{iteration // TOLL_BACKFILL_EVERY_N}] '
                      f'elapsed={bf_elapsed:.1f}s '
                      f'scanned={bf_summary.get("events_scanned", 0)} '
                      f'toll_seen={bf_summary.get("toll_events_seen", 0)} '
                      f'inserted={bf_summary.get("backfilled", 0)} '
                      f'dup={bf_summary.get("skipped_dup", 0)} '
                      f'errors={len(bf_summary.get("errors", []))}',
                      flush=True)
                if bf_summary.get('errors'):
                    for err in bf_summary['errors'][:2]:
                        print(f'    BACKFILL ERR: {err}', flush=True)
            except Exception as e:
                import traceback
                print(f'  [BACKFILL #{iteration // TOLL_BACKFILL_EVERY_N}] '
                      f'EXCEPTION: {e}', flush=True)
                traceback.print_exc()

        # ── JobOrders / ERP Repair Request piggyback sync ───────────
        # Run it after the Cartrack poll (not before) so a JO sync
        # failure can't delay or interfere with the GPS polling loop.
        # The try/except keeps the heartbeat alive even if joborders
        # is misconfigured or the ERP is down.
        if iteration % JOBORDERS_SYNC_EVERY_N == 0:
            jo_started = time.time()
            try:
                from joborders_sync import run_sync as joborders_run_sync
                jo_summary = joborders_run_sync()
                jo_elapsed = time.time() - jo_started
                print(f'  [JO #{iteration // JOBORDERS_SYNC_EVERY_N}] '
                      f'elapsed={jo_elapsed:.1f}s '
                      f'fetched={jo_summary.get("records_fetched", 0)} '
                      f'created={jo_summary.get("created", 0)} '
                      f'updated={jo_summary.get("updated", 0)} '
                      f'unmatched={jo_summary.get("plate_unmatched", 0)} '
                      f'errors={len(jo_summary.get("errors", []))}',
                      flush=True)
                if jo_summary.get('errors'):
                    for err in jo_summary['errors'][:2]:
                        print(f'    JO ERR: {err}', flush=True)
            except Exception as e:
                import traceback
                print(f'  [JO #{iteration // JOBORDERS_SYNC_EVERY_N}] '
                      f'EXCEPTION: {e}', flush=True)
                traceback.print_exc()
                # Same policy — never let a JO sync failure kill the
                # always-on task. The next iteration tries again.

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
