"""Daily SQLite backup for dispatch.db — run as a PythonAnywhere
scheduled task.

Uses sqlite3's online backup API, which takes a consistent snapshot
even while the web app / polling worker are mid-write (a plain file
copy can capture a torn, corrupt database). Backups are written to
backups/dispatch-YYYY-MM-DD.db next to the project, gzip-compressed,
and the newest KEEP_DAYS are retained.

Setup on PythonAnywhere (one time):
  Tasks tab -> Add a new scheduled task, daily at an off-peak hour, eg:
      python3 /home/JDVBBBDARC/dispatch-scheduler/scripts/backup_db.py

Restore procedure (also in docs/EMERGENCY_RUNBOOK.md):
      cd ~/dispatch-scheduler
      gunzip -k backups/dispatch-YYYY-MM-DD.db.gz
      cp dispatch.db dispatch.db.broken        # keep the bad one
      mv backups/dispatch-YYYY-MM-DD.db dispatch.db
      # then reload the web app + restart the always-on task
"""
import gzip
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

DB_PATH    = os.environ.get('DB_PATH', os.path.join(_ROOT, 'dispatch.db'))
BACKUP_DIR = os.environ.get('DB_BACKUP_DIR', os.path.join(_ROOT, 'backups'))
KEEP_DAYS  = int(os.environ.get('DB_BACKUP_KEEP_DAYS', '14'))


def main():
    if not os.path.exists(DB_PATH):
        print(f'ERROR: database not found at {DB_PATH}')
        sys.exit(1)
    os.makedirs(BACKUP_DIR, exist_ok=True)

    stamp = datetime.now().strftime('%Y-%m-%d')
    raw_path = os.path.join(BACKUP_DIR, f'dispatch-{stamp}.db')
    gz_path  = raw_path + '.gz'

    if os.path.exists(gz_path):
        print(f'Backup for {stamp} already exists ({gz_path}) — skipping.')
        return

    # Online backup: consistent snapshot even during concurrent writes.
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(raw_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Sanity check the snapshot before trusting it.
    chk = sqlite3.connect(raw_path)
    try:
        ok = chk.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        chk.close()
    if ok != 'ok':
        os.remove(raw_path)
        print(f'ERROR: snapshot failed integrity_check ({ok}) — aborted.')
        sys.exit(1)

    # Compress (SQLite files squeeze well) and drop the raw copy.
    with open(raw_path, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(raw_path)
    size_mb = os.path.getsize(gz_path) / 1_048_576
    print(f'Backed up {DB_PATH} -> {gz_path} ({size_mb:.1f} MB)')

    # Retention: delete backups older than KEEP_DAYS.
    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    removed = 0
    for name in os.listdir(BACKUP_DIR):
        if not (name.startswith('dispatch-') and name.endswith('.db.gz')):
            continue
        try:
            d = datetime.strptime(name[len('dispatch-'):-len('.db.gz')],
                                  '%Y-%m-%d')
        except ValueError:
            continue
        if d < cutoff:
            os.remove(os.path.join(BACKUP_DIR, name))
            removed += 1
    if removed:
        print(f'Pruned {removed} backup(s) older than {KEEP_DAYS} days.')


if __name__ == '__main__':
    main()
