# Project Handoff / Continuity Notes

> **Purpose:** carry project context across machines and sessions.
> The code lives in git; this file lives in git too, so a fresh
> `git clone` on any laptop instantly restores the "where we are"
> picture. No credentials are in this file — they live only in the
> PythonAnywhere `.env` and Cartrack/ERP web consoles.

## ⭐ First prompt on a new machine (copy-paste this)

Open Claude Code **inside the cloned `dispatch-scheduler` folder**, then
paste:

```
Bago tayo magsimula, i-catch up ka muna sa project na ito:

1. Basahin ang docs/HANDOFF.md — buong project context, features,
   gotchas, at mga naka-pending.
2. Basahin ang docs/WORKLOG.md — kasaysayan ng ginawa namin at bakit.
3. Basahin ang docs/EMERGENCY_RUNBOOK.md — deploy, restart, at
   restore procedures.
4. Patakbuhin: git log --oneline -25 — para makita ang huling ginawa.

Pagkatapos, i-summarize sa akin: (a) ano ang estado ng app ngayon,
(b) ano ang naka-pending, at (c) ano ang dapat kong gawin sa
PythonAnywhere kung may hindi pa na-deploy. Taglish sagot.
```

That single prompt rebuilds the working picture from git alone — no
chat history needed. (Copying `~/.claude/projects/<hash>/` from the old
machine additionally restores the literal transcript, but it is not
required.)

## What this is
Flask + SQLite dispatch scheduler for a trucking fleet (Big Ben
Logistics). Runs on **PythonAnywhere** (account `JDVBBBDARC`), repo
`github.com/JDVBBBDARC/dispatch-scheduler`. Two processes: the **web
app** (Web tab) and the **always-on polling worker** (`cartrack_poll.py`,
Tasks tab) that pulls Cartrack GPS + syncs FixFlo/ERP breakdowns.

## Set up on a new machine
1. `git clone https://github.com/JDVBBBDARC/dispatch-scheduler.git`
2. Nothing else is needed to work on code. To run locally, set
   `FLASK_DEV_INSECURE=1` (ephemeral dev key). Production secrets stay
   on PythonAnywhere.
3. Deploy = push to `main`, then on PA: `git pull` → **Web tab Reload**
   (for templates/app_v3) and/or **restart the always-on worker** (for
   `cartrack_poll.py` / `joborders_sync.py`). Full steps + rollback:
   `docs/EMERGENCY_RUNBOOK.md`.

## Branches — `main` ONLY
One branch. Commit to `main`, push with:

```bash
git push origin main
```

There is no mirror branch and no long-lived feature branch to keep in
sync. (August 2026: nine stale branches were deleted — eight April
feature branches whose tips were already ancestors of `main`, plus the
`feature/cartrack-integration` mirror that had become byte-identical to
it. The dual-push it required is what let work scatter and one commit go
orphaned back in June.) If you ever need a branch for a risky
experiment, make it short-lived, merge it to `main`, then delete it.

## Where things live
| Thing | Location |
|---|---|
| Web app / routes | `app_v3.py` |
| GPS polling + toll detection | `cartrack_poll.py` (worker) |
| ERP breakdown sync | `joborders_sync.py` |
| Toll rate matrix | `static/toll_rates.json` |
| Toll geofence reference | `toll_geofences.json` (96 booth-accurate) |
| DB | `dispatch.db` (SQLite, project root on PA) |
| Nightly DB backup | `scripts/backup_db.py` → `backups/` (2AM PHT task) |
| User manual (v1.8) | `docs/manual/` → PDF at repo root |
| Ops survival guide (Taglish) | `docs/EMERGENCY_RUNBOOK.md` |

## Major features shipped (mid-2026)
- **Cartrack GPS toll detection** — 96 booth-accurate geofences; entry→
  exit trip pairing; 45-min idle-close; per-vehicle-class fees; Toll Log
  page + GPS-Toll dashboard KPI (reconciliation only, never billing).
- **Excel schedule import** (Schedule → Import Excel) — reads 4 tabs of
  the monthly monitoring workbook; auto-creates master data with
  name-variant matching; per-category wave sequencing; automatic trip
  types incl. **Hustling** (12W/22WD hauling → OT, out of utilisation);
  duplicate-safe; one-click Revert. Rules in `api_schedule_import_xlsx`.
- **Dashboard** — 8 KPI cards with previous-period trend deltas;
  drag/resize chart panels (localStorage); date filters via Apply
  button; Fleet Utilisation excludes OT.
- **Schedule table** — Excel-style resizable columns + row copy/paste
  across waves/days; Reference & Toll columns removed.
- **Printable reports** — Breakdown JO summary bucketed by repair
  category (`_JO_CATEGORIES`); Schedule materials/volume summary. Both
  in `templates/reports/`.
- **Daily DB backup**, **breakdown-sync health banners**.

## Hard-won gotchas (don't re-learn these)
- **Firebase live-refresh** needs `firebase-admin` installed for the
  web app's Python. It vanished after a PA Python upgrade and died
  silently. Now pinned in `requirements.txt`. Symptom: no auto-refresh /
  no activity toasts. Fix: `pip3.X install --user firebase-admin` + Reload.
- **Toll geofences that sit on the SCTEX mainline** falsely catch
  drive-through traffic and corrupt trip pairing. Ignored in
  `_IGNORED_TOLL_GEOFENCES` (cartrack_poll.py): legacy `Toll - Clark`
  AND `Toll - Clark South` (mainline ~46m from booth — no radius
  separates them). Watch for others; the tell is a plaza appearing on
  trips that never used it.
- **ERP breakdown sync** must not null-out manually-linked plates, and
  matches plates alphanumerically (DT-32 == DT32). A dead sync now
  shows a red banner on the Breakdown page + Driver/Truck-Ratio hint.
- **Import dates are strict** — text like "Cancelled" in a date cell is
  skipped, not defaulted to today (that once created phantom trips).
- Store timestamps are **naive UTC**; Cartrack API speaks **PHT**.
  PHT = UTC+8. Mixing them up has bitten diagnostics twice.

## Open / pending

- 🔴 **BLOCKER — PA is checked out on a branch that no longer exists.**
  The PA console prompt reads
  `~/dispatch-scheduler (feature/cartrack-integration)`, but that remote
  branch was deleted in the August 2026 cleanup (`e875b08`). So
  `git pull` on PA now **fails** ("no such ref was fetched") and
  **nothing since the cleanup is deployed** — including the offline-mode
  fixes (root-scoped service worker, lapsed-session queue loss,
  broken-server-vs-cached-page, stale-cache banner, clipboard expiry).
  Fix, in a PA Bash console — check first, don't blindly switch:

  ```bash
  cd ~/dispatch-scheduler
  python scripts/backup_db.py     # snapshot first
  git status                      # any uncommitted work ON PA?
  git branch -a                   # does a local `main` exist?
  ```

  If `git status` is clean:

  ```bash
  git fetch origin --prune
  git checkout main               # creates it tracking origin/main
  git branch -u origin/main main
  git pull
  git branch -D feature/cartrack-integration   # drop the dead local branch
  touch /var/www/jdvbbbdarc_pythonanywhere_com_wsgi.py
  ```

  Then restart the always-on worker (worker code changed too), and
  hard-refresh the browser (`Ctrl+Shift+R`) so the new service worker
  takes over. If `git status` is NOT clean, inspect and preserve those
  changes before switching — PA is production.

- 🟠 **The production DB has never been copied off PythonAnywhere.**
  `dispatch.db` and its nightly `backups/*.db.gz` both live inside the PA
  account, so losing the account loses the data and every backup with it.
  The nightly task is healthy (14 unbroken nights as of 2026-08-20, ~1.1 MB
  gzipped). Fix is manual, ~5 minutes, from any machine with a browser:
  PA → Files → `dispatch-scheduler/backups/` → download the newest
  `.db.gz` → keep a copy off-host (external drive + the Google Drive
  folder "Dispatch Scheduler — OFFSITE BACKUP"). Verify the copy after
  downloading (`gzip -t`, then `PRAGMA integrity_check`) — an unverified
  backup is not a backup. Worth repeating monthly.

- **TH02 (NGU7958, cartrack_id 31524271) logged Bocaue instead of
  Balagtas** as entry (2026-07-20 ~22:57 PHT). Balagtas geofence is
  small (94m) vs Bocaue's large (227m). Diagnosing whether Balagtas was
  missed (→ resize it, carefully) or the truck never passed it (→ Bocaue
  correct) via `scripts/diag_track.py 31524271 "2026-07-20 22:30"
  "2026-07-20 23:10"`. Awaiting output.
- 45-min idle window can still merge/split some long-haul trips —
  parking-lot item; proper fix = close-on-home/customer-geofence.
- Diagnostics: `scripts/diag_plate_toll.py <BODY>` (local toll history),
  `scripts/diag_track.py <cartrack_id> <PHT start> <PHT end>` (raw track
  vs booths).

## Continuing the Claude Code conversation on a new laptop
The chat transcript + Claude's project memory are LOCAL, under
`~/.claude/projects/<project-path-hash>/` (the `.jsonl` files and the
`memory/` folder). Copy that folder to the new machine to keep
`claude --resume` history; but because the path hash includes the OS
username, the durable context is really this file + git history + the
per-commit messages. A fresh session that reads this HANDOFF is caught
up.
