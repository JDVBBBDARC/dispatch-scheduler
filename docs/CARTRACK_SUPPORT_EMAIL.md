# Email template — Cartrack PH support: API geofence visibility issue

**To:** support@cartrack.ph (or your Cartrack PH account manager)
**Subject:** Fleet REST API user cannot see all geofences in our account

---

Hi Cartrack PH support team,

We use the Cartrack Fleet REST API (`fleetapi-ph.cartrack.com`) to read
geofence and vehicle data for an internal dispatch and toll-tracking
application. We've identified a permission discrepancy and need help
resolving it.

## The issue

Our API user account can only see **107 of our 168 geofences** when
calling `/rest/geofences`. The remaining **61 geofences are visible
in the Fleet Web UI** to our human users but are completely absent
from the API response, regardless of pagination, sort, or filter
parameters we've tried.

## Specific example

A geofence named **"Toll - Balagtas"** exists in our Fleet Web UI
(owner: `BIGB00011`, last updated 2026-05-12 17:11) but never appears
in the API response across any combination of `page`, `per_page`,
`sort`, `order_by`, `archived`, or `status` query parameters.

## What we've ruled out

- **Pagination bug** — we deduplicate by `geofence_id` on our side;
  the 107 unique cap holds across all parameter variants.
- **Sort order** — tried `sort=name`, `sort=geofence_id`,
  `sort_by=name`, `order_by=name`, ascending and descending; same 107
  every time.
- **Archived flag** — tried `archived=0`, `archived=1`,
  `include_archived=1`, `visible=all`; same 107 every time.

## What we suspect

The API user account has restricted geofence visibility — possibly:

1. A per-user `geofence_scope` or `account_id` filter that limits the
   user to a subset of the account's geofences;
2. Sub-account boundaries that aren't crossed by the REST API even
   though the web UI displays the full set;
3. Owner / `created_by` filtering at the API layer that we cannot
   override via query parameters.

## What we need

Please grant our API user (username: **<YOUR_API_USERNAME_HERE>**)
**full read access to all geofences** in our account, matching the
visibility the same user has in the web UI.

If a single-user expansion isn't possible, please advise:

- Whether we need a separate API account with `admin` scope;
- Whether the geofences need to be re-created under our API user;
- Whether there's a `sub_account_id` parameter we should be passing.

Happy to provide our API username, account ID, a sample request, and
a diff of the visible vs hidden geofence names if helpful.

Thank you,

**<YOUR NAME>**
**Big Ben Logistics**
**<YOUR PHONE / EMAIL>**

---

## Notes for filing this ticket

1. **Replace `<YOUR_API_USERNAME_HERE>`** with the actual `CARTRACK_USERNAME`
   value from your PA `.env` file.
2. **Replace `<YOUR NAME>` and contact info** before sending.
3. If they ask for diagnostic logs, attach the output of:
   ```
   python scripts/debug_geofence_sort_test.py
   ```
4. Expected resolution time: **1–3 business days** for Cartrack PH support
   based on typical SLAs.
