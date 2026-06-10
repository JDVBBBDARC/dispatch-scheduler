"""Probe Cartrack's /rest/geofences with different sort/filter params
to find a query that exposes the geofences hidden by the default
pagination.

Background: in the default fetch order, Cartrack returns ~108 unique
geofences but claims total=168. After page 10 it returns duplicates of
the first 10 pages. Try several alternative params to find one that
actually walks the full set.

Each variant:
  - Fetches all pages
  - Dedupes by geofence_id
  - Reports unique count + whether 'Toll - Balagtas' is found
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _bootstrap_env():
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
        for p in glob.glob('/var/www/*_pythonanywhere_com_wsgi.py'):
            with open(p) as f:
                for line in f:
                    s = line.strip()
                    if s.startswith('os.environ[') and '=' in s:
                        try: exec(s, {'os': os})
                        except Exception: pass
            break
    except Exception:
        pass


_bootstrap_env()


# Parameter variants to try. None means "no extra params, just page=N".
VARIANTS = [
    {'label': 'default',          'params': {}},
    {'label': 'sort=name',        'params': {'sort': 'name'}},
    {'label': 'sort=-name',       'params': {'sort': '-name'}},
    {'label': 'sort=geofence_id', 'params': {'sort': 'geofence_id'}},
    {'label': 'order_by=name',    'params': {'order_by': 'name'}},
    {'label': 'order=asc',        'params': {'order': 'asc'}},
    {'label': 'order=desc',       'params': {'order': 'desc'}},
    {'label': 'sort_by=name',     'params': {'sort_by': 'name'}},
    {'label': 'status=active',    'params': {'status': 'active'}},
    {'label': 'archived=0',       'params': {'archived': '0'}},
    {'label': 'archived=1',       'params': {'archived': '1'}},
    {'label': 'visible=all',      'params': {'visible': 'all'}},
    {'label': 'include_archived=1', 'params': {'include_archived': '1'}},
]

TARGET = 'toll - balagtas'   # the canary name we're looking for


def walk_pages(cc, extra_params):
    """Fetch all pages with given extra params, dedupe by geofence_id."""
    seen = set()
    unique = []
    page = 1
    while page <= 25:    # cap to avoid runaway
        params = {'page': page}
        params.update(extra_params)
        status, body = cc._call('/rest/geofences', params=params)
        if status != 200 or not isinstance(body, dict):
            return unique, f'HTTP {status} at page {page}'
        data = body.get('data', [])
        for g in data:
            gid = g.get('geofence_id') or g.get('id') or g.get('name')
            if gid in seen:
                continue
            seen.add(gid)
            unique.append(g)
        meta = body.get('meta') or {}
        if meta.get('current_page', page) >= meta.get('last_page', 1):
            break
        page += 1
    return unique, None


def main():
    try:
        from cartrack_client import CartrackClient
    except Exception as e:
        print(f'Import failed: {e}')
        return 1

    cc = CartrackClient.from_env()
    if not cc.configured:
        print('Cartrack not configured. Set .env or WSGI env vars.')
        return 1

    print(f'Probing /rest/geofences for "{TARGET}" with parameter variants...')
    print(f'{"VARIANT":<25} {"UNIQUE":>6}  {"FOUND_TARGET":<14}  ERROR')
    print('-' * 80)

    results = []
    for v in VARIANTS:
        unique, err = walk_pages(cc, v['params'])
        found = any(TARGET in (g.get('name') or '').lower() for g in unique)
        marker = 'YES' if found else 'no'
        err_s = err or ''
        print(f'{v["label"]:<25} {len(unique):>6}  {marker:<14}  {err_s}')
        results.append((v['label'], len(unique), found, unique))

    # If any variant found the target, dump the names from that one
    winners = [r for r in results if r[2]]
    if winners:
        label, count, _, unique = winners[0]
        print()
        print(f'WINNER: variant "{label}" exposed {count} unique geofences '
              f'including the target.')
        print('All names from that variant (sorted):')
        for n in sorted({(g.get("name") or "").strip() for g in unique if g.get("name")}):
            mark = ' <-- target' if TARGET in n.lower() else ''
            print(f'  {n}{mark}')
    else:
        print()
        print('NO variant exposed "Toll - Balagtas".')
        print('The geofence may be in a sub-account/folder not visible to '
              'this API user, or may have been hidden by a Cartrack-side '
              'visibility setting. Check the Cartrack admin UI for the '
              'geofence detail and confirm the "owner" / "group" attribute.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
