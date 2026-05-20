"""
Cartrack Fleet API client for the dispatch_scheduler.

Reads credentials from environment variables (NEVER hardcoded):
    CARTRACK_USERNAME   - API username from Cartrack Fleet Web Settings
    CARTRACK_PASSWORD   - API password from same
    CARTRACK_BASE_URL   - optional, defaults to 'https://fleetapi-ph.cartrack.com'
    CARTRACK_INSECURE_SSL - optional, set to '1' to bypass SSL verification
                            (only needed behind corporate proxies)

Usage:
    from cartrack_client import CartrackClient

    cc = CartrackClient.from_env()
    if not cc.configured:
        # Credentials not set — return early or skip integration features

    vehicles  = cc.list_vehicles()       # list of vehicle dicts
    positions = cc.get_status()          # current positions + geofence_ids
    geofences = cc.list_geofences()      # all geofences in account

All methods return (None, error_message) on failure for graceful handling.
"""
import os
import sys
from datetime import datetime, timedelta


class CartrackClient:
    """Thin wrapper over the Cartrack Fleet REST API."""

    def __init__(self, username, password,
                 base_url='https://fleetapi-ph.cartrack.com',
                 insecure_ssl=False, timeout=15):
        self.username     = username or ''
        self.password     = password or ''
        self.base_url     = (base_url or 'https://fleetapi-ph.cartrack.com').rstrip('/')
        self.insecure_ssl = insecure_ssl
        self.timeout      = timeout
        self._session     = None      # lazy init

    @property
    def configured(self):
        """Return True if both username and password are set."""
        return bool(self.username and self.password)

    @classmethod
    def from_env(cls):
        """Build a client from CARTRACK_* environment variables."""
        return cls(
            username=os.environ.get('CARTRACK_USERNAME', ''),
            password=os.environ.get('CARTRACK_PASSWORD', ''),
            base_url=os.environ.get('CARTRACK_BASE_URL',
                                    'https://fleetapi-ph.cartrack.com'),
            insecure_ssl=os.environ.get('CARTRACK_INSECURE_SSL', '0') in ('1', 'true', 'True'),
        )

    def _session_obj(self):
        """Lazy-create the requests Session (auto-installs requests if missing)."""
        if self._session is not None:
            return self._session

        try:
            import requests
        except ImportError:
            import subprocess
            subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                                   '--quiet', 'requests'])
            import requests

        # Suppress insecure-request warning if needed
        if self.insecure_ssl:
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass

        s = requests.Session()
        # NOTE: Do NOT set s.trust_env = False here. On PythonAnywhere free tier,
        # outbound HTTPS goes through their proxy (HTTPS_PROXY env var) which
        # enforces the whitelist. Bypassing it would fail with [Errno 111]
        # Connection refused even after the host is whitelisted. We keep
        # trust_env at its default (True) so requests honors the proxy.
        s.verify    = not self.insecure_ssl
        s.auth      = (self.username, self.password)
        s.headers.update({
            'Accept':     'application/json',
            'User-Agent': 'dispatch-scheduler-cartrack/1.0',
        })
        self._session = s
        return s

    def _call(self, path, method='GET', **kwargs):
        """Make a REST call. Returns (status_code, parsed_body_or_error_str)."""
        if not self.configured:
            return None, 'CartrackClient not configured (missing CARTRACK_USERNAME/PASSWORD env vars)'

        try:
            import requests
        except ImportError:
            return None, 'requests library not installed'

        url = self.base_url + path
        try:
            resp = self._session_obj().request(method, url, timeout=self.timeout, **kwargs)
            try:
                return resp.status_code, resp.json()
            except ValueError:
                return resp.status_code, resp.text
        except requests.Timeout:
            return None, f'Cartrack API timeout ({self.timeout}s) on {path}'
        except requests.RequestException as e:
            return None, f'Cartrack API error on {path}: {e}'

    # ─────────────────────────────────────────────────────────────
    # Public methods — high-level data access
    # ─────────────────────────────────────────────────────────────

    def list_vehicles(self):
        """Return the list of vehicles in the account — handles pagination.

        Cartrack's /rest/vehicles returns 10 records per page by default and
        exposes pagination via a 'meta' object: {'current_page', 'last_page',
        'per_page', 'total'}. We loop through all pages and concatenate.

        Returns:
            (list_of_vehicle_dicts, None) on success
            (None, error_string) on failure
        """
        all_vehicles = []
        page = 1
        while True:
            status, body = self._call('/rest/vehicles', params={'page': page})
            if status != 200 or not isinstance(body, dict):
                return None, f'list_vehicles HTTP {status}: {body}'
            data = body.get('data', [])
            all_vehicles.extend(data)
            meta = body.get('meta', {}) if isinstance(body.get('meta'), dict) else {}
            current_page = meta.get('current_page', page)
            last_page    = meta.get('last_page', 1)
            if current_page >= last_page:
                break
            page += 1
            # Safety guard — never fetch more than 100 pages
            if page > 100:
                break
        return all_vehicles, None

    def get_status(self):
        """Return current status (position + geofence_ids) for all vehicles."""
        status, body = self._call('/rest/vehicles/status')
        if status != 200 or not isinstance(body, dict):
            return None, f'get_status HTTP {status}: {body}'
        return body.get('data', []), None

    def list_geofences(self):
        """Return all geofences in the account — paginated with dedup.

        Cartrack /rest/geofences paginates and exposes pagination via a
        'meta' object. We loop through all pages and concatenate.

        Two robustness measures against Cartrack's pagination instability
        (observed in the field: 168 records claimed total, but some items
        appear on two consecutive pages while others are skipped entirely
        — likely caused by an unstable sort key when records are updated
        during the fetch window):

          1. Request a large per_page so we finish before any records can
             shift. Most Cartrack endpoints accept per_page up to 200.
          2. Deduplicate by geofence_id on the way in, so any cross-page
             duplicates collapse to a single row.

        Returns:
            (list_of_geofence_dicts, None) on success
            (None, error_string) on failure
        """
        seen_ids = set()
        all_geofences = []
        page = 1
        per_page = 200      # large window — usually fetches everything in 1 call
        while True:
            status, body = self._call('/rest/geofences',
                                       params={'page': page,
                                               'per_page': per_page})
            if status != 200 or not isinstance(body, dict):
                return None, f'list_geofences HTTP {status}: {body}'
            data = body.get('data', [])
            for g in data:
                gid = g.get('geofence_id') or g.get('id') or g.get('name')
                if gid in seen_ids:
                    continue
                seen_ids.add(gid)
                all_geofences.append(g)
            meta = body.get('meta', {}) if isinstance(body.get('meta'), dict) else {}
            current_page = meta.get('current_page', page)
            last_page    = meta.get('last_page', 1)
            if current_page >= last_page:
                break
            page += 1
            if page > 100:   # safety guard
                break
        return all_geofences, None

    def list_trips(self, start_dt=None, end_dt=None):
        """Return trip records in the date range — handles pagination.

        Cartrack expects timestamps as 'Y-m-d H:i:s' (NOT ISO 8601).
        Defaults to last 24h. Loops through all pages of results.
        """
        now = datetime.now()
        start_dt = start_dt or (now - timedelta(days=1))
        end_dt   = end_dt or now
        base_params = {
            'start_timestamp': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'end_timestamp':   end_dt.strftime('%Y-%m-%d %H:%M:%S'),
        }
        all_trips = []
        page = 1
        while True:
            params = dict(base_params, page=page)
            status, body = self._call('/rest/trips', params=params)
            if status != 200 or not isinstance(body, dict):
                return None, f'list_trips HTTP {status}: {body}'
            data = body.get('data', [])
            all_trips.extend(data)
            meta = body.get('meta', {}) if isinstance(body.get('meta'), dict) else {}
            current_page = meta.get('current_page', page)
            last_page    = meta.get('last_page', 1)
            if current_page >= last_page:
                break
            page += 1
            if page > 100:   # safety guard
                break
        return all_trips, None

    def get_events(self, start_dt=None, end_dt=None):
        """Return vehicle events in the date range — handles pagination.

        Defaults to last hour. Loops through all pages of results.
        """
        now = datetime.now()
        start_dt = start_dt or (now - timedelta(hours=1))
        end_dt   = end_dt or now
        base_params = {
            'start_timestamp': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'end_timestamp':   end_dt.strftime('%Y-%m-%d %H:%M:%S'),
        }
        all_events = []
        page = 1
        while True:
            params = dict(base_params, page=page)
            status, body = self._call('/rest/vehicles/events', params=params)
            if status != 200 or not isinstance(body, dict):
                return None, f'get_events HTTP {status}: {body}'
            data = body.get('data', [])
            all_events.extend(data)
            meta = body.get('meta', {}) if isinstance(body.get('meta'), dict) else {}
            current_page = meta.get('current_page', page)
            last_page    = meta.get('last_page', 1)
            if current_page >= last_page:
                break
            page += 1
            if page > 100:   # safety guard
                break
        return all_events, None

    # ─────────────────────────────────────────────────────────────
    # Convenience helpers
    # ─────────────────────────────────────────────────────────────

    def find_vehicle_by_plate(self, plate_no):
        """Return the Cartrack vehicle dict whose registration matches the plate.

        Matches loosely — strips spaces, dashes, case. e.g.,
            'NEX 8020' matches 'DT01 - NEX8020' or 'NEX8020' etc.
        """
        vehicles, err = self.list_vehicles()
        if err:
            return None, err
        norm = _norm_plate(plate_no)
        if not norm:
            return None, 'empty plate_no'
        for v in vehicles:
            # Cartrack exposes plate identifiers in multiple fields:
            #   'registration'  — compact form, e.g. 'DT06-LAK8098' or 'NKR9373'
            #   'vehicle_name'  — display form, e.g. 'DT06 - LAK8098'
            #   'name'          — alternate display field used in some accounts
            for field in ('registration', 'vehicle_name', 'name'):
                if _norm_plate(v.get(field) or '').endswith(norm):
                    return v, None
                if norm in _norm_plate(v.get(field) or ''):
                    return v, None
        return None, f'no Cartrack vehicle found matching plate "{plate_no}"'


def _norm_plate(s):
    """Normalize a plate string for fuzzy matching."""
    return ''.join(c for c in (s or '').upper() if c.isalnum())
