"""Audit the user's Cartrack-side toll geofences.

Fetches every geofence from Cartrack via the configured API client and
classifies them against the canonical plaza list in toll_rates.json.

Output groups:
    [OK]       Recognised toll plazas — name matches an entry in the
               fee matrix (will work for auto-fill).
    [NEAR]     Possibly mistyped — name looks like a toll plaza but
               doesn't match any matrix key. Suggests the closest match.
    [UNKNOWN]  Has "Toll" prefix but no matrix entry — typo or new plaza.
    [NON-TOLL] Geofence is NOT toll-named (skipped, no action needed).
    [MISSING]  Matrix plazas that have no corresponding Cartrack geofence.
               Prioritised — NLEX/SCTEX first.

Run from project root:
    python scripts/audit_toll_geofences.py

If running locally and env vars aren't set, the script will try to
bootstrap them from the PA WSGI file at ~/dispatch-scheduler/wsgi.py
(only relevant if you're on PythonAnywhere bash console).
"""
import json
import os
import sys
from difflib import get_close_matches
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _bootstrap_env():
    """Load env vars from .env file (project root) then from the PA WSGI
    file. Identical to the helper in cartrack_poll.py — duplicated here
    so the script runs as a standalone tool without importing the
    polling module.

    Already-set env vars are never overwritten."""
    # 1. .env file at project root
    try:
        env_path = ROOT / '.env'
        if env_path.exists():
            with open(env_path, encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#') or '=' not in s:
                        continue
                    key, _, val = s.partition('=')
                    key = key.strip()
                    val = val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                        val = val[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass

    # 2. PA WSGI fallback
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
                        exec(stripped, {'os': os})
                    except Exception:
                        pass
    except Exception:
        pass


_bootstrap_env()


def load_expected_plazas():
    """Return {plaza_name: expressway_key} from the fee matrix."""
    with open(ROOT / 'static' / 'toll_rates.json', encoding='utf-8') as f:
        data = json.load(f)
    plaza_to_exp = {}
    for exp_key, exp_data in data.items():
        if not isinstance(exp_data, dict):
            continue
        for k, v in exp_data.items():
            if isinstance(k, str) and k.startswith('Class ') and isinstance(v, dict):
                for plaza in v.keys():
                    plaza_to_exp.setdefault(plaza, exp_key)
    return plaza_to_exp


def _clean_and_resolve(name):
    """Use cartrack_poll's own helpers so audit and runtime stay in
    perfect lockstep. Returns (canonical, confidence) where confidence
    is 1.0 for exact, 0.95 for accent/case match, 0.85-0.94 for fuzzy."""
    try:
        from cartrack_poll import (_clean_plaza_name, _resolve_plaza)
    except Exception:
        # Should never happen — fail loud if it does.
        raise
    cleaned = _clean_plaza_name(name)
    canonical, conf = _resolve_plaza(cleaned)
    return cleaned, canonical, conf


def is_toll_named(name):
    """True if the geofence name looks like a toll plaza."""
    if not name:
        return False
    u = name.upper()
    return (u.startswith('TOLL ')
            or u.startswith('TOLLBOOTH')
            or ' TOLL ' in u
            or u.endswith(' TOLL'))


def main():
    # Pull geofences from Cartrack. We use the CartrackClient directly so
    # the script works without the Flask app running.
    try:
        from cartrack_client import CartrackClient
    except Exception as e:
        print(f'Could not import cartrack_client: {e}')
        return 1

    cc = CartrackClient.from_env()
    if not cc.configured:
        print('Cartrack not configured — set CARTRACK_USERNAME and '
              'CARTRACK_PASSWORD env vars first.')
        print()
        print('On PA bash console:')
        print('  export CARTRACK_USERNAME=...')
        print('  export CARTRACK_PASSWORD=...')
        print('  python scripts/audit_toll_geofences.py')
        return 1

    print('Fetching geofences from Cartrack...')
    geofences, err = cc.list_geofences()
    if err:
        print(f'list_geofences failed: {err}')
        return 1
    print(f'Got {len(geofences or [])} geofences from Cartrack.')
    print()

    # Build expected plaza list.
    expected = load_expected_plazas()
    expected_names = sorted(expected.keys())

    # Classify each Cartrack geofence using the same resolver the
    # polling worker uses, so the audit reflects exactly what would
    # auto-fill at runtime.
    ok_exact, ok_fuzzy, unknown, non_toll = [], [], [], []
    seen_plazas = set()
    for g in (geofences or []):
        name = (g.get('name') or '').strip()
        if not is_toll_named(name):
            non_toll.append(name)
            continue
        cleaned, canonical, conf = _clean_and_resolve(name)
        if canonical is None:
            # No match even with fuzzy — manual rename needed.
            # Still show closest suggestion based on cleaned name.
            suggestion = get_close_matches(cleaned, expected_names, n=1, cutoff=0.5)
            unknown.append((name, cleaned,
                            suggestion[0] if suggestion else None,
                            expected.get(suggestion[0]) if suggestion else None))
            continue
        # Resolved — bucket by confidence
        seen_plazas.add(canonical)
        if conf >= 0.95:
            ok_exact.append((name, canonical, expected.get(canonical, '?'), conf))
        else:
            ok_fuzzy.append((name, cleaned, canonical,
                             expected.get(canonical, '?'), conf))

    # Compute missing — group by expressway and prioritise NLEX/SCTEX.
    missing_by_exp = {}
    for plaza, exp in expected.items():
        if plaza not in seen_plazas:
            missing_by_exp.setdefault(exp, []).append(plaza)
    priority_order = [
        'NLEX_SCTEX', 'Skyway_SLEX_MCX', 'NLEX_Connector',
        'Harbor_Link', 'TPLEX', 'CALAX', 'CAVITEX',
        'STAR', 'Skyway_Stage3', 'NAIAX',
    ]

    # ── Report ────────────────────────────────────────────────────────
    total_ok = len(ok_exact) + len(ok_fuzzy)
    print('=' * 76)
    print(f'CARTRACK GEOFENCE AUDIT — {len(geofences or [])} total geofences')
    print('=' * 76)
    print(f'  [OK-EXACT] {len(ok_exact):>3}  Exact/normalised match — will auto-fill')
    print(f'  [OK-FUZZY] {len(ok_fuzzy):>3}  Fuzzy match — will auto-fill (review suggested)')
    print(f'  [UNKNOWN]  {len(unknown):>3}  No match — manual rename needed')
    print(f'  [NON-TOLL] {len(non_toll):>3}  Non-toll geofences (skipped)')
    print(f'  [MISSING]  {sum(len(v) for v in missing_by_exp.values()):>3}  Plazas with no Cartrack geofence')
    print()

    if ok_exact:
        print('─' * 76)
        print('[OK-EXACT] These geofences resolve cleanly and auto-fill will fire:')
        print('─' * 76)
        for name, canonical, exp, conf in sorted(ok_exact, key=lambda x: x[1]):
            marker = '=' if conf == 1.0 else '~'
            print(f'  ✓ {name:<35} {marker}> {canonical:<25} ({exp})')
        print()

    if ok_fuzzy:
        print('─' * 76)
        print('[OK-FUZZY] These resolved via fuzzy match. Auto-fill works, but consider')
        print('           renaming for cleaner audit trails:')
        print('─' * 76)
        for name, cleaned, canonical, exp, conf in ok_fuzzy:
            print(f'  ~ {name!r}')
            print(f'      cleaned -> {cleaned!r}')
            print(f'      matched -> "{canonical}" ({exp}) at confidence {conf:.2f}')
        print()

    if unknown:
        print('─' * 76)
        print('[UNKNOWN] Could not match against any fee-matrix plaza. Rename in Cartrack:')
        print('─' * 76)
        for name, cleaned, suggestion, exp in unknown:
            print(f'  ? {name!r}  (cleaned: {cleaned!r})')
            if suggestion:
                print(f'      closest guess: "Toll - {suggestion}" ({exp})')
            else:
                print(f'      no suggestion — verify this is actually a toll plaza')
        print()

    if missing_by_exp:
        print('─' * 76)
        print('[MISSING] Top priority plazas you have NOT yet created in Cartrack:')
        print('─' * 76)
        for exp in priority_order:
            plazas = missing_by_exp.get(exp, [])
            if not plazas:
                continue
            print(f'  {exp}  ({len(plazas)} missing):')
            for p in sorted(plazas):
                print(f'      - Toll - {p}')
            print()

    if non_toll:
        print('─' * 76)
        print(f'[NON-TOLL] {len(non_toll)} non-toll geofences (skipped, not audited):')
        print('─' * 76)
        # Show first 10 only — usually customer/quarry/etc.
        for name in non_toll[:10]:
            print(f'    {name}')
        if len(non_toll) > 10:
            print(f'    ... and {len(non_toll) - 10} more')
        print()

    print('=' * 76)
    print('SUMMARY:')
    print(f'  Toll auto-fill will fire for {total_ok} geofences ({len(ok_exact)} exact + {len(ok_fuzzy)} fuzzy).')
    if unknown:
        print(f'  {len(unknown)} unmatched geofences — manual rename needed.')
    if missing_by_exp:
        total_missing = sum(len(v) for v in missing_by_exp.values())
        print(f'  Create {total_missing} more for full coverage.')
    print('=' * 76)
    return 0


if __name__ == '__main__':
    sys.exit(main())
