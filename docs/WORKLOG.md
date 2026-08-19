# Work Log — what was built, and why

> A running chronicle of the development conversation behind this repo, so
> the *reasoning* travels with the code to any machine. Read together with
> `docs/HANDOFF.md` (current state) and `git log` (per-change detail — the
> commit messages carry the full rationale for each fix).
>
> **Deliberately contains no operational data** (no driver/client names,
> plate numbers, volumes, coordinates, or credentials). This repo is
> public; the raw chat transcript is NOT committed for that reason. See
> "Keeping the literal transcript" at the end.

---

## June 2026 — GPS toll detection made real

**The problem.** Toll fees were encoded by hand from receipts, with no
independent check. GPS-based detection existed but was unusable: the plaza
coordinates came from public data and averaged ~4.3 km off — one marker
famously sat on a residential compound.

**What we did.**
- Built a coordinate pipeline (`integration_doc/build_toll_geofences.py`)
  merging three sources: the fences hand-drawn in the GPS platform (booth
  level), OpenStreetMap `barrier=toll_booth` positions, and the original
  worksheet. Result: 59 booth-accurate + 41 OSM-refined + 28 unverified,
  rendered on a 3-tier map so the gaps were visible.
- Wrote an activation script to create the missing fences through the GPS
  vendor's API. The POST schema wasn't documented, so it ran staged:
  dry-run → `--inspect` (print a real record to learn the field names) →
  `--create-one` → `--create-all`. The 422 response told us the field was
  `polygon`, not `polygon_wkt`. All **96 fences** ended up live, averaging
  **5 m** from the OSM booth positions.
- Hardened the event backfill against the vendor's 429 rate limits
  (page pacing, retry, partial results).

**Bugs found and fixed along the way.**
- **PHT vs UTC date filters.** Twelve filter bounds compared a Philippine
  calendar date against UTC-stored timestamps, so every event between
  midnight and 08:00 PHT — the fleet's busiest hours — was invisible.
- **Plaza name resolution.** The name cleaner stripped trailing direction
  words, collapsing "Clark North"/"Clark South" (both real fee-matrix
  keys) into a "Clark" that matched nothing; and "Florida" never reached
  "Floridablanca". Fees silently came out blank.
- **Missing rate row** for one NLEX plaza, filled from the open-system
  fare zone its neighbours already encoded.
- **21 unprotected API routes** — anyone could mutate schedule data
  without logging in. All now require auth.
- **Driver/Truck Ratio history.** Repairs flipped to "Fixed" stopped
  subtracting the truck from *past* trend days, so history rewrote itself.

**The lesson that kept recurring: geofences on the mainline.** A fence
positioned where the expressway passes within tens of metres of the booth
catches drive-through traffic. It first split one real trip into two
fragments, then corrupted trip pairing outright. Fixed by an explicit
ignore list — with the event coordinates measured first to prove the
mainline really was ~46 m from the booth, i.e. that no radius could
separate them.

---

## June–July 2026 — the dashboard becomes usable

- Charts made **draggable and resizable** with per-browser saved layout.
  Three follow-ups came from real use: panels stretched to match their
  row-neighbour (fixed with `align-items`), the resize grip was covered by
  the chart canvas so nothing could actually be resized (replaced with a
  custom drag bar), and resizing needed to work horizontally too.
- **KPI trend deltas** — every card compares to the previous equal-length
  period, coloured by *meaning* rather than direction (more Delivered is
  green; more Breakdown Hours is red).
- **Performance:** the Activity Trend issued one COUNT query per day per
  truck type (~115 per load, ~240 for a 30-day range). Collapsed into
  three GROUP BYs.
- Date filters moved behind an **Apply** button — picking "From" used to
  reload the page before "To" could be set.
- **Fleet Utilisation excludes the OT category**, because hauling is
  deliberately out of scope for utilisation.
- Rebranded to dark maroon across app and manual.

---

## July 2026 — the monthly workbook stops being retyped

The month's schedule lived in a spreadsheet and was re-encoded by hand.
Now it imports.

- Reads **four tabs**, each with its own header dialect, matched by header
  text so a moved column doesn't break the import.
- **Preview → Import Now**, plus a **one-click revert** (every import is
  journaled with the ids it created).
- Business rules encoded from operations' own vocabulary: wave number
  follows each plate's Nth trip *within its category*; trip type derives
  from the client; internal hauling by the two dump-trailer classes is
  **"Hustling"**, filed out of utilisation.
- **Name-variant matching** so spelling differences don't create duplicate
  master data (initial+surname key plus a fuzzy-surname fallback).
- **Duplicate-safe**: the same or an updated workbook can be re-uploaded
  weekly without doubling anything.

**Two data-integrity catches here were significant.**
1. Volume was mapped to the *purchase-order total*, which repeats on every
   row of that order — so each trip claimed the whole month's volume.
   Remapped to the per-trip loaded volume.
2. Rows whose date cell held the *text* "Cancelled" fell through a lenient
   date parser that defaulted to *today*, inventing phantom trips dated
   the day of the import. Date parsing is strict now; unparseable rows are
   skipped and counted.

A cleanup script was needed for the first import (it predated the revert
feature). Because it deletes data, it was reviewed adversarially before
use — that review found a **critical** flaw: the "this row came from the
import" heuristic also matched rows restored from the spreadsheet backup,
which would have deleted hand-entered work. It now refuses to run on a
database with a restore in its history unless explicitly forced.

---

## July 2026 — reliability and reporting

- **Nightly database backup** (`scripts/backup_db.py`): consistent
  snapshot via SQLite's online backup API, integrity-checked, gzipped,
  14-day retention, run as a scheduled task. Restore steps documented.
- **Printable reports**: job orders grouped by *kind of repair* (free-text
  descriptions bucketed by keyword, then listed numbered inside each
  category), and a materials/volume summary for any date range.
- **ERP breakdown sync** stopped losing plate links: the upsert rewrote
  `plate_id` on every run, so a link made by hand was wiped on the next
  sync and the breakdown vanished from the dashboard again and again.
  Matching is now punctuation-tolerant, with a re-link pass that heals old
  rows.
- **A dead sync is loud now.** It used to fail silently and serve
  days-old data with no signal anywhere.

**The Firebase outage** taught the same lesson from a different angle:
live refresh had quietly died because a package vanished during a hosting
Python upgrade, and the app's graceful "skip if unavailable" meant nobody
noticed. Now pinned in `requirements.txt` and written into the
troubleshooting guide.

---

## August 2026 — offline mode

**The ask:** keep working when the host is down or there's no internet —
read everywhere, write on the Schedule.

Built in two phases: a reachability heartbeat plus page caching, then an
offline write queue that replays in order on recovery (mapping temporary
negative ids to the real ids the server assigns; conflict policy is
last-write-wins by replay, chosen by operations).

**Every one of the following was found by testing in a real browser, and
each would have shipped broken:**

1. **The service worker never controlled any page.** Registered from
   `/static/sw.js`, its scope was `/static/` — it could not intercept
   navigation to any real page. Offline mode was a silent no-op, and it
   *looked* fine because the cache existed. Now served from a root route.
2. **A lapsed session silently discarded queued edits.** On sync, the
   POST was redirected to the login page, which answers `200`, so the
   queue counted it a success and dropped the work. Reproduced live: a
   wave and trip queued offline vanished with nothing written.
3. **"Prepare Offline" couldn't help in the case that mattered** —
   arriving with no connection, when you can no longer press it. Caching
   now happens automatically whenever the app is used online.
4. **A broken server beat a good cached page.** The fallback only ran when
   the connection *failed*; a host that accepts the connection and answers
   with an empty body (the `ERR_EMPTY_RESPONSE` the user actually hit)
   made the fetch *succeed*, and that useless response was passed straight
   through while a perfect cached copy sat unused.
5. **A stale copy was indistinguishable from live data** — which is how
   deleted rows appeared to come back and new work appeared to vanish.
   Cached pages now carry the time they were captured and say so, and the
   app re-fetches the live page automatically once the server returns.
6. **The row clipboard was immortal**, so a copy from days earlier still
   pasted. Given an expiry — and then the expiry itself had a bug that let
   exactly the pre-existing (undated) entries live forever.

---

## Recurring themes worth carrying forward

- **Silent degradation is the enemy.** Nearly every long-lived bug here
  hid behind something that "failed gracefully": Firebase skipped, sync
  died, a geofence resolved to nothing, a redirect counted as success.
  Anything that can stop working invisibly now says so on screen.
- **Verify against the real thing.** Reasoning about service workers,
  cache semantics and vendor APIs produced confident wrong answers; a
  browser and a deliberately-broken server produced the truth.
- **Timezones and identity keys are where data quietly breaks** —
  PHT vs UTC, `DT-32` vs `DT32`, "Clark" vs "Clark South".

---

## Keeping the literal transcript

The chat transcript is **not** in this repo on purpose: it contains
operational data (people, clients, plates, volumes, yard coordinates) and
this repository is public.

If you want the verbatim history on a new machine, copy the local folder
`~/.claude/projects/<project-path-hash>/` (the `.jsonl` files plus
`memory/`) by hand — USB or private cloud storage, not git. It is not
required: this file plus `HANDOFF.md` plus the commit messages reconstruct
the reasoning.
