"""Diagnostic: dump every geofence name returned by the Cartrack API,
plus per-page pagination stats. Used to debug 'why is X missing from
the audit' questions.

Run from project root:
    python scripts/debug_geofence_fetch.py [search_term]

Optional `search_term` filters output to names containing that string
(case-insensitive). Without it, ALL names are printed.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _bootstrap_env():
    """Same as cartrack_poll._bootstrap_env_from_wsgi — load .env then
    fall back to the PA WSGI file."""
    try:
        env_path = ROOT / '.env'
        if env_path.exists():
            with open(env_path, encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#') or '=' not in s:
                        continue
                    key, _, val = s.partition('=')
                    key = key.strip(); val = val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                        val = val[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass
    try:
        import glob
        candidates = glob.glob('/var/www/*_pythonanywhere_com_wsgi.py')
        if candidates:
            with open(candidates[0]) as f:
                for line in f:
                    s = line.strip()
                    if s.startswith('os.environ[') and '=' in s:
                        try:
                            exec(s, {'os': os})
                        except Exception:
                            pass
    except Exception:
        pass


_bootstrap_env()


def main():
    search = sys.argv[1].lower() if len(sys.argv) > 1 else None

    try:
        from cartrack_client import CartrackClient
    except Exception as e:
        print(f'Import failed: {e}')
        return 1

    cc = CartrackClient.from_env()
    if not cc.configured:
        print('Cartrack not configured. Check .env or WSGI env vars.')
        return 1

    # Manually walk pages instead of using list_geofences() so we can
    # report per-page counts. Mirrors the same logic.
    print('Fetching geofences from Cartrack (paginated)...')
    print()
    all_names = []
    page = 1
    while True:
        status, body = cc._call('/rest/geofences', params={'page': page})
        if status != 200 or not isinstance(body, dict):
            print(f'  Page {page}: HTTP {status} — STOPPING')
            print(f'    Body: {body}')
            break
        data = body.get('data', [])
        meta = body.get('meta', {}) if isinstance(body.get('meta'), dict) else {}
        current = meta.get('current_page', page)
        last    = meta.get('last_page', 1)
        total   = meta.get('total', '?')
        per     = meta.get('per_page', '?')
        print(f'  Page {current}/{last}: {len(data)} geofences  '
              f'(per_page={per}, total={total})')
        for g in data:
            name = (g.get('name') or '').strip()
            if name:
                all_names.append(name)
        if current >= last:
            break
        page += 1
        if page > 100:
            print('  (safety limit hit at page 100)')
            break

    print()
    print(f'TOTAL geofences fetched: {len(all_names)}')
    print()

    # Filter and print
    if search:
        matches = [n for n in all_names if search in n.lower()]
        print(f'─ Names containing {search!r} ({len(matches)}) ─')
        for n in sorted(matches):
            print(f'  {n}')
    else:
        # Just list them all sorted
        print('─ All geofence names (sorted) ─')
        for n in sorted(all_names):
            print(f'  {n}')

    # Specifically check for Balagtas
    print()
    print('─ Specific check: any name containing "Balagtas" ─')
    found = [n for n in all_names if 'balagtas' in n.lower()]
    if found:
        for n in found:
            print(f'  FOUND: {n!r}')
    else:
        print('  NOT FOUND — geofence not in API response (pagination or '
              'permission issue).')

    return 0


if __name__ == '__main__':
    sys.exit(main())
