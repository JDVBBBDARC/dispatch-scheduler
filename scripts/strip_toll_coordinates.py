"""One-time script to remove the `coordinates` sub-blocks from
static/toll_rates.json. They were used by the now-disabled
coordinate-based toll plaza detection; the fee matrix remains.

A backup is written to static/toll_rates.json.bak before saving.

Run from project root:
    python scripts/strip_toll_coordinates.py
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / 'static' / 'toll_rates.json'
BAK  = SRC.with_suffix('.json.bak')


def main():
    if not SRC.exists():
        print(f'Source not found: {SRC}')
        return

    # Back up first.
    shutil.copy2(SRC, BAK)
    print(f'Backup: {BAK}')

    with open(SRC, 'r', encoding='utf-8') as f:
        data = json.load(f)

    removed = 0
    plaza_count = 0
    for exp_key, exp_block in data.items():
        if isinstance(exp_block, dict) and 'coordinates' in exp_block:
            plaza_count += len(exp_block['coordinates'])
            del exp_block['coordinates']
            removed += 1

    with open(SRC, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    before = BAK.stat().st_size
    after  = SRC.stat().st_size
    print(f'Stripped coordinates from {removed} expressway(s) '
          f'({plaza_count} plaza coordinate entries).')
    print(f'File size: {before:,} bytes -> {after:,} bytes '
          f'(-{before - after:,} bytes).')


if __name__ == '__main__':
    main()
