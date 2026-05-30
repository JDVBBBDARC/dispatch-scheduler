"""ERP Repair Request API client.

Thin Python wrapper around the gainersand.ph ERP repair-request endpoints.
Mirrors the structure of cartrack_client.py — same env-var bootstrap pattern,
same configured/from_env/error-tuple conventions — so the codebase stays
consistent and future readers don't have to learn a new style.

Credentials live in the project-root `.env` file:

    JOBORDERS_BASE_URL=https://erp-api.gainersand.ph/api
    JOBORDERS_TOKEN=<service-account-bearer-token>

The token is a long-lived service-account bearer token issued by the ERP
backend team. If the API ever returns 401, raise a clear error so the
operator knows to rotate the token — refresh-flow integration can be added
later if the team moves to short-lived tokens.

Endpoint coverage (per the Postman collection IT shared, May 29 2026):

    GET /repair-request/list?filter=<status>&search=<ref_no>&from=<date>&to=<date>
    GET /repair-request/{id}/show
    GET /repair-request/complete/list
    GET /repair-request/released/list

This client exposes the list + show endpoints (the two the sync worker
needs). The other endpoints are available if/when we extend later.

All public methods return (data, error) tuples:
    data  — parsed JSON body on success (dict or list, depends on endpoint)
    error — None on success, string error on failure

This convention lets callers do:

    rows, err = client.list_repair_requests(filter='approved')
    if err:
        log.warning('list_repair_requests failed: %s', err)
        return
    for row in rows:
        ...

without exception-handling boilerplate at every call site.
"""
import os
import sys


class JobOrdersClient:
    """Thin wrapper over the ERP Repair Request REST API."""

    def __init__(self, token, base_url=None, timeout=15):
        self.token    = (token or '').strip()
        self.base_url = (base_url
                         or 'https://erp-api.gainersand.ph/api').rstrip('/')
        self.timeout  = timeout
        self._session = None   # lazy

    # ─────────────────────────────────────────────────────────────────
    # Setup
    # ─────────────────────────────────────────────────────────────────

    @property
    def configured(self):
        """True if both base_url and token look usable."""
        return bool(self.token and self.base_url)

    @classmethod
    def from_env(cls):
        """Build a client from JOBORDERS_* environment variables.

        Returns an unconfigured client (configured=False) if the env vars
        are missing — callers should check `configured` before use.
        """
        return cls(
            token=os.environ.get('JOBORDERS_TOKEN', ''),
            base_url=os.environ.get('JOBORDERS_BASE_URL',
                                    'https://erp-api.gainersand.ph/api'),
        )

    def _session_obj(self):
        """Lazy-create the requests.Session (auto-installs requests if missing).

        Mirrors cartrack_client._session_obj — same pip-install fallback,
        same trust_env=True policy (so PA's outbound HTTPS_PROXY whitelist
        keeps working without any explicit configuration on our side).
        """
        if self._session is not None:
            return self._session

        try:
            import requests
        except ImportError:
            import subprocess
            subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                                   '--quiet', 'requests'])
            import requests

        s = requests.Session()
        # NOTE: do NOT set s.trust_env = False — PA routes outbound HTTPS
        # through their proxy and the whitelist depends on those env vars.
        s.auth = None
        s.headers.update({
            'Accept':        'application/json',
            'Authorization': f'Bearer {self.token}',
            'User-Agent':    'dispatch-scheduler-joborders/1.0',
        })
        self._session = s
        return s

    # ─────────────────────────────────────────────────────────────────
    # Internal HTTP wrapper
    # ─────────────────────────────────────────────────────────────────

    def _call(self, path, method='GET', **kwargs):
        """Make a REST call. Returns (status_code, parsed_body_or_error_str).

        Mirrors the cartrack_client._call shape so the sync worker can use
        the same response-handling pattern.
        """
        if not self.configured:
            return None, ('JobOrdersClient not configured — '
                          'JOBORDERS_TOKEN env var missing')

        try:
            import requests
        except ImportError:
            return None, 'requests library not installed'

        url = self.base_url + path
        try:
            resp = self._session_obj().request(method, url,
                                                timeout=self.timeout, **kwargs)
            try:
                return resp.status_code, resp.json()
            except ValueError:
                # Non-JSON response (e.g., HTML error page from a misrouted URL).
                return resp.status_code, resp.text
        except requests.Timeout:
            return None, f'JobOrders API timeout ({self.timeout}s) on {path}'
        except requests.RequestException as e:
            return None, f'JobOrders API error on {path}: {e}'

    # ─────────────────────────────────────────────────────────────────
    # Public methods
    # ─────────────────────────────────────────────────────────────────

    def list_repair_requests(self, filter=None, search=None,
                              from_date=None, to_date=None):
        """List repair requests with optional filters.

        Per the Postman collection from IT:
            GET /repair-request/list?filter=<status>&search=<ref_no>
                                    &from=<YYYY-MM-DD>&to=<YYYY-MM-DD>

        Args:
            filter:    one of '' (all), 'pending', 'approved', 'rejected'
            search:    substring search on equipment ref_no (e.g., 'D26C0')
            from_date: ISO date string 'YYYY-MM-DD' (inclusive start)
            to_date:   ISO date string 'YYYY-MM-DD' (inclusive end)

        Returns:
            (list_or_dict, None) on success — shape depends on what the
                                  ERP backend actually returns. Likely
                                  either a top-level array or
                                  {data: [...], meta: {...}}.
            (None, error_string) on failure
        """
        params = {}
        # `filter` is always sent — empty string means "all", per the
        # Postman docs. Omitting it might 400 on some servers.
        params['filter'] = filter or ''
        if search:    params['search'] = search
        if from_date: params['from']   = from_date
        if to_date:   params['to']     = to_date

        status, body = self._call('/repair-request/list', params=params)
        if status is None:
            return None, body                      # transport-level error
        if status == 401:
            return None, ('JobOrders 401 — service token rejected. '
                          'Rotate JOBORDERS_TOKEN in the .env file.')
        if status >= 400:
            return None, f'list_repair_requests HTTP {status}: {body}'
        return body, None

    def get_repair_request(self, rr_id):
        """Fetch a single repair request by ID.

        Per the Postman collection:
            GET /repair-request/{id}/show

        Returns:
            (data_dict, None) on success — typically {data: {...},
                                            message: 'maintenanceRequest.show'}
            (None, error_string) on failure
        """
        try:
            rr_id = int(rr_id)
        except (ValueError, TypeError):
            return None, f'get_repair_request: invalid id {rr_id!r}'

        status, body = self._call(f'/repair-request/{rr_id}/show')
        if status is None:
            return None, body
        if status == 401:
            return None, ('JobOrders 401 — service token rejected. '
                          'Rotate JOBORDERS_TOKEN in the .env file.')
        if status == 404:
            return None, f'repair-request #{rr_id} not found'
        if status >= 400:
            return None, f'get_repair_request HTTP {status}: {body}'
        return body, None


# ─────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────
# Usage on PythonAnywhere:
#     python -c "from joborders_client import _smoke; _smoke()"
#
# Output is intentionally terse — meant to confirm "token works" and
# "endpoint reachable" without leaking response details onto the screen.
# ─────────────────────────────────────────────────────────────────────

def _smoke():
    """Manual smoke test — verify the client can reach the API + auth."""
    # Try the cartrack-style env bootstrap (so this script picks up .env
    # values when run as a standalone command on PA).
    try:
        from cartrack_poll import _bootstrap_env_from_wsgi
        _bootstrap_env_from_wsgi()
    except Exception:
        pass   # not fatal — env may already be populated

    cc = JobOrdersClient.from_env()
    print(f'JOBORDERS_BASE_URL  = {cc.base_url}')
    print(f'JOBORDERS_TOKEN set = {"YES" if cc.token else "NO"} '
          f'({len(cc.token)} chars)')
    print(f'configured          = {cc.configured}')
    if not cc.configured:
        return

    data, err = cc.list_repair_requests(filter='')
    if err:
        print(f'LIST result: ERROR — {err}')
    else:
        if isinstance(data, dict):
            keys = list(data.keys())
            print(f'LIST result: OK  — dict with keys {keys}')
            # Try common pagination wrappers without dumping payloads
            for key in ('data', 'items', 'results'):
                if key in data:
                    arr = data[key]
                    if isinstance(arr, list):
                        print(f'  -> {key}: list of {len(arr)} items')
        elif isinstance(data, list):
            print(f'LIST result: OK  — list of {len(data)} items')
        else:
            print(f'LIST result: OK  — unexpected shape {type(data).__name__}')


if __name__ == '__main__':
    _smoke()
