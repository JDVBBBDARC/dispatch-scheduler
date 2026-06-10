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
    # report per-page counts AND show pagination duplicates. The
    # production client now dedupes — this script keeps the raw view
    # so anomalies are visible.
    print('Fetching geofences from Cartrack (raw, with per_page=200)...')
    print()
    raw_records = []           # every record as returned, including dupes
    seen_ids = set()
    unique_records = []         # deduped by geofence_id
    duplicate_pairs = []        # (id, name) for cross-page duplicates

    # Per Cartrack PH support: /rest/geofences accepts a `limit` param
    # that bypasses pagination entirely. The `per_page` we tried earlier
    # is silently ignored — that's why our pagination loop was capping
    # at varying totals (105/107/108). Use limit=1000 to fetch everything
    # in one call.
    status, body = cc._call('/rest/geofences', params={'limit': 1000})
    if status != 200 or not isinstance(body, dict):
        print(f'  HTTP {status} — STOPPING')
        print(f'  Body: {body}')
        return 1
    data = body.get('data', [])
    meta = body.get('meta', {}) if isinstance(body.get('meta'), dict) else {}
    total   = meta.get('total', '?')
    per     = meta.get('per_page', '?')
    for g in data:
        gid = g.get('geofence_id') or g.get('id') or g.get('name')
        raw_records.append(g)
        if gid in seen_ids:
            duplicate_pairs.append((gid, (g.get('name') or '').strip()))
            continue
        seen_ids.add(gid)
        unique_records.append(g)
    print(f'  Single call (limit=1000): {len(data)} geofences  '
          f'(meta.total={total}, meta.per_page={per})')

    all_names = [(g.get('name') or '').strip() for g in unique_records
                 if (g.get('name') or '').strip()]

    print()
    print(f'RAW    geofences returned by API: {len(raw_records)}')
    print(f'UNIQUE geofences (deduped by ID): {len(unique_records)}')
    if duplicate_pairs:
        print()
        print(f'Cross-page duplicates ({len(duplicate_pairs)}):')
        for gid, name in duplicate_pairs[:20]:
            print(f'  - id={gid}  name={name!r}')
        if len(duplicate_pairs) > 20:
            print(f'  ... and {len(duplicate_pairs) - 20} more')
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
