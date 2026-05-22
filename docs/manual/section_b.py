"""Section B — User Manual (9 modules)."""
from reportlab.platypus import PageBreak
from reportlab.lib.units import cm
from helpers import (h_section, h1, h2, h3, p, pj, lead, sp, code,
                      bullet_list, numbered_list, std_table, callout,
                      screenshot_placeholder, S)


def section_b():
    out = []
    out.append(PageBreak())
    out.append(h_section('Section B — User Manual'))
    out.append(lead(
        'This section is a step-by-step operating guide for each of the '
        'nine modules in the Dispatch Scheduler. Each subsection follows '
        'the same template: an introduction, a screen-by-screen walk '
        'through of the user interface, the most common tasks performed '
        'in the module, and any quality-control checks the user must '
        'perform before considering a task complete.'))

    # ── B.0 Login ──────────────────────────────────────────────────────
    out.append(h1('B.0 Login and Session Management'))
    out.append(pj(
        'Every page of the application requires authentication. '
        'Visiting any URL without an active session redirects the '
        'browser to the login screen.'))
    out.append(h2('Logging In'))
    for x in numbered_list([
        'Open a web browser and navigate to the application URL provided '
        'by the IT Administrator.',
        'Enter your assigned username in the <b>Username</b> field.',
        'Enter your password in the <b>Password</b> field. Passwords are '
        'case-sensitive.',
        'Click <b>Sign In</b>. On success you will be redirected to the '
        'Dashboard.',
    ]): out.append(x)
    out.append(screenshot_placeholder('Login screen',
                                          image='login.png', height_cm=9))
    out.append(h2('Logging Out'))
    out.append(p('Click your username in the top-right corner of any '
                  'page, then choose <b>Sign Out</b>. Always sign out '
                  'when leaving a shared workstation unattended.'))
    out.append(callout(
        'Password Confidentiality',
        'Do not share your password with any colleague, including '
        'supervisors. Passwords must be changed at least every ninety '
        'days, and immediately if a compromise is suspected. Report any '
        'suspected unauthorised access to the IT Administrator within '
        'one business day.',
        kind='warn'))

    # ── B.1 Dashboard ──────────────────────────────────────────────────
    out.append(h1('B.1 Dashboard'))
    out.append(pj(
        'The Dashboard is the default landing page after login. It '
        'provides a real-time snapshot of operations for the current '
        'business day. The data refreshes automatically every sixty '
        'seconds, so the figures shown reflect the latest information '
        'available without manual reloading.'))
    out.append(screenshot_placeholder(
        'Dashboard overview — KPI cards, fleet utilisation, breakdown chart, '
        'truck cycle widget', image='dashboard.png', height_cm=11))

    out.append(h2('KPI Cards'))
    out.append(p('Four headline indicators sit at the top of the page. '
                  'Each card is clickable and opens a drill-down dialog '
                  'showing the underlying trips.'))
    kpi_rows = [
        ['KPI', 'Definition', 'Drill-down'],
        ['Trips Today',    'Count of TripRecord rows with a Wave date equal to today, excluding cancelled trips.', 'List of today\'s trips with status, plate, driver, client.'],
        ['Toll Fee',       'Sum of toll_fee across today\'s non-cancelled trips. <b>Manual entry only</b> — dispatcher records each trip\'s toll from the physical receipt or RFID statement.', 'Same trip list with toll figures highlighted.'],
        ['GPS Toll',       'Sum of toll fees computed by the polling worker from GPS plaza transits today. <b>Independent of Toll Fee</b> — purely reference / audit. Finance can compare the two to spot exemptions, missed transits, or RFID glitches.', 'Click the card to open the Toll Log page.'],
        ['Delivered',      'Count of trips with status = Delivered.',                                                'Filtered list of completed trips only.'],
        ['Fleet Util. %',  'Earned points divided by daily target points across all plates with at least one assignment.','Per-plate breakdown of points earned.'],
    ]
    out.append(std_table(kpi_rows, col_widths=[3.3 * cm, 6.7 * cm, 6.5 * cm]))

    out.append(callout(
        'Toll Fee vs GPS Toll',
        'Two distinct KPIs by design. <b>Toll Fee</b> is what dispatchers '
        'manually record from receipts (this is what Finance bills). '
        '<b>GPS Toll</b> is what our polling worker auto-detected from '
        'plaza transits — it is a reference figure, not a billing input. '
        'Daily reconciliation (SOP-004) compares the two to catch '
        'discrepancies that warrant investigation (e.g., a transit the '
        'GPS detected but no manual entry exists, or vice-versa).',
        kind='iso'))

    out.append(h2('Fleet Utilisation Chart'))
    out.append(pj(
        'The horizontal bar chart shows each truck type\'s percentage '
        'of daily target points achieved. Each truck type has a '
        'per-leg point value (typically 1.0, or 0.5 for ten-wheelers) '
        'and a daily target (typically 1.5, or 4.0 for ten-wheelers). '
        'Bars are colour-coded green (≥100%), amber (70–99%), and red '
        '(below 70%).'))

    out.append(h2('Driver-Truck Ratio'))
    out.append(pj(
        'Compares the number of available drivers against the number '
        'of assigned plates per truck category. A ratio below 1.0 '
        'indicates plates outnumber qualified drivers and surfaces '
        'staffing gaps that require attention.'))

    out.append(h2('Breakdown Hours Chart'))
    out.append(pj(
        'Stacked bar chart of total breakdown hours per plate over a '
        'configurable look-back window (default seven days). Used to '
        'identify chronically unreliable plates that may need '
        'preventative maintenance or replacement.'))

    out.append(h2('Truck Cycle Time Widget'))
    out.append(pj(
        'Four mini-statistics: Open Cycles (trucks currently away from '
        'BIG BEN SCM), Closed Today, Average Cycle Hours over the past '
        'seven days, and Long Cycles (those exceeding twenty-four '
        'hours). Click the <b>Open Truck Cycle Time</b> button to '
        'jump to the dedicated cycle-time analytics page.'))

    out.append(callout(
        'Data Quality',
        'Dashboard figures are only as accurate as the underlying trip '
        'data. Dispatchers must update trip statuses promptly. Trips '
        'left at "Pending" or "In Transit" after delivery cause the '
        'Delivered count to under-report. See SOP-002 (End-of-Day '
        'Reconciliation).',
        kind='warn'))

    # ── B.2 Schedule ──────────────────────────────────────────────────
    out.append(h1('B.2 Schedule'))
    out.append(pj(
        'The Schedule module is where the daily trip plan is built, '
        'updated, and closed out. It is the most heavily used module '
        'in the application and the primary tool of the dispatch team.'))

    out.append(h2('Layout'))
    out.append(p('The Schedule page is organised by truck type. Each '
                  'truck type has its own tab at the top of the page '
                  '(e.g., DT, TH, MDT, L300). Selecting a tab shows '
                  'all Waves scheduled for that truck type on the '
                  'current date.'))
    out.append(screenshot_placeholder(
        'Schedule page — truck-type tabs, Wave panels with trip rows',
        image='schedule.png', height_cm=11))

    out.append(h2('Navigating Between Dates'))
    out.append(p('Use the date picker at the top of the page. Selecting '
                  'a new date reloads the schedule for that date '
                  'without losing your current truck-type tab.'))

    out.append(h2('Creating a New Wave'))
    out.append(pj(
        'A Wave is a grouping of trips on the same date and truck '
        'type. Most days have a single Wave per truck type, but '
        'multiple waves are supported (e.g., morning and afternoon '
        'dispatches).'))
    for x in numbered_list([
        'Select the desired date and truck-type tab.',
        'If no waves exist yet, click the <b>+ Add 1st Wave</b> button '
        'in the empty state.',
        'If a wave already exists and you need a second, click the '
        '<b>+ New Wave</b> button at the top of the truck-type panel.',
        'A wave label is automatically assigned (e.g., "Wave 1", "Wave 2").',
    ]): out.append(x)

    out.append(h2('Adding a Trip Row'))
    for x in numbered_list([
        'Click <b>+ Add Row</b> at the bottom of the Wave panel.',
        'A new editable row appears with empty fields.',
        'Fill in the fields from left to right. Required fields: Driver, '
        'Plate, Product, Client. Optional but recommended: Helper, '
        'Dispatcher, RS No., PO No., DR No., Volume.',
        'Set the Status — typically "Pending" at creation time.',
        'Enter the Toll Fee if known in advance; otherwise leave at 0 '
        'and let the GPS auto-fill populate it.',
        'Click anywhere outside the row to commit the changes. Saves '
        'occur automatically per field on blur.',
    ]): out.append(x)

    out.append(h2('Editing an Existing Trip'))
    out.append(p('All fields are inline-editable. Click on the field, '
                  'type or select the new value, then click outside the '
                  'field. Changes save automatically. There is no '
                  '"Save" button — this design eliminates the risk of '
                  'losing edits.'))

    out.append(h2('Duplicating a Trip'))
    out.append(pj(
        'Use the copy icon (📋) at the start of each trip row to '
        'duplicate the row. The copy carries all field values (driver, '
        'helper, plate, product, client, dispatcher, RS/PO/DR numbers, '
        'volume, status, notes, toll fee) so dispatchers can rapidly '
        'create similar trips and tweak only the differences.'))
    out.append(h3('Duplicate to the same wave (default)'))
    out.append(p('Single-click the copy icon. A new row appears at the '
                  'bottom of the same wave, highlighted briefly in '
                  'yellow. Edit the few fields that differ (typically '
                  'RS / PO / DR numbers).'))
    out.append(h3('Duplicate to a different wave'))
    out.append(pj(
        'When two or more waves exist for the truck type on the same '
        'date (e.g., morning and afternoon dispatches), the copy icon '
        'shows a small caret beside it. Click the caret to open a '
        'short menu listing every wave, with the current one marked '
        '"(here)". Pick the target wave to copy the row there. A '
        'toast confirms the destination (e.g., "Copied to 2nd Wave").'))
    out.append(callout(
        'Cross-wave copy speeds up multi-shift planning',
        'Same client + product + plate + driver but split across AM '
        'and PM shifts is a common pattern. Use the cross-wave copy '
        'to clone the AM trip into the PM wave with one click; only '
        'the RS/PO/DR numbers need updating. See SOP-001 for the '
        'standard daily dispatch flow.',
        kind='ok'))

    out.append(h2('Updating Trip Status'))
    out.append(p('The Status badge cycles through the four operational '
                  'states when clicked: <b>Pending → Loading → In '
                  'Transit → Delivered</b>. To set a non-linear status '
                  '(e.g., Cancelled), use the dropdown control instead.'))
    status_rows = [
        ['Status',     'Meaning', 'When to set'],
        ['Pending',    'Trip planned but not yet started.',          'At trip creation, or when reverting an incorrect status.'],
        ['Loading',    'Truck is at the origin loading cargo.',      'When the driver radios in at the loading point.'],
        ['In Transit', 'Truck is en route to the customer.',          'When the truck departs the loading point.'],
        ['Delivered',  'Cargo has been received and signed for.',     'On confirmation from the driver / customer.'],
        ['Cancelled',  'Trip was assigned but did not run.',          'When a customer cancels, or weather / breakdown prevents execution.'],
    ]
    out.append(std_table(status_rows,
                          col_widths=[2.6 * cm, 5.2 * cm, 8.7 * cm]))

    out.append(h2('Deleting a Trip'))
    out.append(p('Click the red trash icon at the right end of the trip '
                  'row. A confirmation dialog appears. Deletions are '
                  'permanent and bypass the audit trail; prefer '
                  '"Cancelled" status for trips that did not run for '
                  'historical reasons.'))
    out.append(callout(
        'Deletion vs Cancellation',
        'Use <b>Delete</b> only for rows created in error (typo, '
        'duplicate). For trips that were planned but did not run, set '
        'the status to <b>Cancelled</b> instead. This preserves the '
        'audit trail and surfaces operational issues in the cancellation '
        'rate KPI.',
        kind='warn'))

    # ── B.3 Master Data ───────────────────────────────────────────────
    out.append(h1('B.3 Master Data'))
    out.append(pj(
        'The Master Data module manages the reference data used '
        'throughout the application: people (drivers, helpers, '
        'dispatchers), assets (plates, truck types), products, clients, '
        'and GPS mappings. Master data changes are infrequent but '
        'high-impact: an incorrect entry here propagates to every '
        'trip that references it.'))
    out.append(screenshot_placeholder(
        'Master Data overview — cards for each entity type',
        image='master.png', height_cm=11))

    out.append(h2('Entity Cards'))
    out.append(p('Each entity (drivers, helpers, plates, etc.) is '
                  'displayed as a card with a header and a list of '
                  'rows. Each card provides three actions: <b>Add</b>, '
                  '<b>Edit</b>, and <b>Deactivate</b>.'))

    out.append(h2('Adding a Driver'))
    for x in numbered_list([
        'Locate the <b>Drivers</b> card.',
        'Click <b>+ Add Driver</b>.',
        'Enter the driver\'s full name.',
        'Select one or more truck types the driver is qualified to operate.',
        'Confirm the <b>Active</b> toggle is on.',
        'Click <b>Save</b>.',
    ]): out.append(x)

    out.append(h2('Adding a Plate'))
    for x in numbered_list([
        'Locate the <b>Plate Numbers</b> card.',
        'Click <b>+ Add Plate</b>.',
        'Enter the registration plate number (e.g., NHF9508) in upper case.',
        'Enter the body number (e.g., DT15) — the internal identifier.',
        'Select the truck type from the dropdown.',
        'Optionally map to a Cartrack vehicle ID for GPS tracking — '
        'see B.3.4.',
        'Click <b>Save</b>.',
    ]): out.append(x)

    out.append(h2('Mapping Plates to Cartrack GPS Devices'))
    out.append(pj(
        'For GPS-driven features (auto toll fill, cycle tracking, live '
        'status) to work, each plate must be linked to its '
        'corresponding Cartrack vehicle. The link is established by '
        'setting the plate\'s <b>cartrack_vehicle_id</b>.'))
    for x in numbered_list([
        'Click the <b>Auto-map all</b> button in the Plates card toolbar. '
        'The system attempts to match each plate to a Cartrack vehicle '
        'by registration number.',
        'Review the response — the system reports how many plates were '
        'matched, how many were ambiguous, and how many remained '
        'unmatched.',
        'For unmatched plates, click the broadcast icon (📡) beside the '
        'plate and pick the correct Cartrack vehicle from the dropdown.',
        'Verify the cyan <b>CT #</b> badge appears beside the plate '
        'after mapping is complete.',
    ]): out.append(x)
    # Plates card lives inside master.png shown above — avoid a redundant
    # placeholder. A second figure is not added here.

    out.append(h2('Deactivating a Master Data Record'))
    out.append(pj(
        'Historical records that are no longer in use should be '
        '<b>deactivated</b>, not deleted. Deactivation removes the '
        'entity from dropdowns on new trip rows but preserves it for '
        'historical reporting. To deactivate, toggle the <b>Active</b> '
        'switch on the entity row to off.'))

    # ── B.4 Breakdown ─────────────────────────────────────────────────
    out.append(h1('B.4 Breakdown'))
    out.append(pj(
        'The Breakdown module records every event that removes a '
        'plate from operational service: mechanical failures, '
        'accident damage, scheduled maintenance, and other downtime '
        'causes. It is the primary record of fleet reliability.'))
    out.append(screenshot_placeholder(
        'Breakdown module — incident table and log form',
        image='breakdown.png', height_cm=10))

    out.append(h2('Logging a Breakdown'))
    for x in numbered_list([
        'Navigate to <b>Breakdown</b> in the left sidebar.',
        'Click <b>+ Log Breakdown</b>.',
        'Select the affected plate.',
        'Enter the start date and time of the incident.',
        'Choose the status: <b>Under Repair</b>, <b>Fixed</b>, or <b>Standby</b>.',
        'Enter a short description of the cause.',
        'Optionally attach the resolution and the end date and time once known.',
        'Click <b>Save</b>.',
    ]): out.append(x)

    out.append(h2('Updating Repair Status'))
    out.append(p('Re-open the breakdown record. Change the status, '
                  'enter the end date and time, and add the resolution '
                  'description. Total downtime is calculated '
                  'automatically as the difference between start and '
                  'end timestamps.'))

    out.append(h2('Breakdown Categories'))
    bd_rows = [
        ['Status',       'Meaning'],
        ['Under Repair', 'Plate is currently with a mechanic or in the shop. Not available for dispatch.'],
        ['Fixed',        'Repair is complete. Plate is back in service.'],
        ['Standby',      'Plate is operational but intentionally held out of service (e.g., waiting for parts, scheduled inspection).'],
    ]
    out.append(std_table(bd_rows, col_widths=[3.5 * cm, 13 * cm]))
    out.append(callout(
        'Same-Day Reporting',
        'Breakdowns must be logged within twenty-four hours of '
        'occurrence. Delayed reporting distorts fleet-availability '
        'metrics and complicates payroll calculations for affected '
        'drivers. See SOP-003 (Breakdown Reporting).',
        kind='iso'))

    # ── B.5 Toll Calculator ───────────────────────────────────────────
    out.append(h1('B.5 Toll Calculator'))
    out.append(pj(
        'The Toll Calculator computes the expected toll fee between '
        'any two plazas on any supported expressway. It uses the same '
        'fee matrix that powers the GPS auto-fill feature, so manual '
        'and automatic figures are always consistent.'))
    out.append(screenshot_placeholder(
        'Toll Calculator — expressway selector, plaza dropdowns, '
        'computed fee display', image='toll_calculator.png', height_cm=10))

    out.append(h2('Computing a Single-Expressway Fee'))
    for x in numbered_list([
        'Choose the expressway from the dropdown (e.g., NLEX / SCTEX).',
        'Choose the vehicle class (Class 1, 2, or 3).',
        'Choose the entry plaza.',
        'Choose the exit plaza.',
        'The fee appears below the form, in Philippine pesos.',
    ]): out.append(x)

    out.append(h2('Multi-Expressway Routing'))
    out.append(p('For trips that span multiple expressways (e.g., NLEX '
                  '→ SCTEX → CALAX), the calculator performs a graph '
                  'search to find a valid route and sums the toll fees '
                  'along the way. Intermediate plazas at expressway '
                  'junctions are inferred automatically.'))

    out.append(h2('Supported Expressways'))
    exp_rows = [
        ['Expressway',           '# Plazas'],
        ['NLEX / SCTEX',         '31'],
        ['Skyway / SLEX / MCX',  '22'],
        ['TPLEX',                '11'],
        ['NAIAX',                '9'],
        ['STAR Tollway',         '8'],
        ['CALAX',                '7'],
        ['Skyway Stage 3',       '7'],
        ['CAVITEX',              '5'],
        ['Harbor Link',          '5'],
        ['NLEX Connector',       '3'],
        ['<b>Total</b>',         '<b>108</b>'],
    ]
    out.append(std_table(exp_rows, col_widths=[10 * cm, 6.5 * cm]))

    # ── B.6 Toll Log ──────────────────────────────────────────────────
    out.append(h1('B.6 Toll Log'))
    out.append(pj(
        'The Toll Log is a chronological list of every plaza-detection '
        'event captured by the GPS polling worker. Each event records '
        'the plate, expressway, plaza, event type (Enter or Exit), and '
        'timestamp. When the system pairs an Enter event with a '
        'subsequent Exit event at a different plaza, the matching '
        'trip is identified and its toll_fee is auto-filled.'))
    out.append(screenshot_placeholder(
        'Toll Log page — KPI cards, filter panel, events table',
        image='toll_log.png', height_cm=11))

    out.append(h2('KPI Cards'))
    for x in bullet_list([
        '<b>Plaza Enters</b> — count of ENTER events in the selected '
        'date range.',
        '<b>Plaza Exits</b> — count of EXIT events in the selected '
        'date range.',
        '<b>Trips Auto-Filled</b> — count of TripRecords whose '
        'toll_fee was populated by the GPS worker.',
        '<b>Toll Fees Today</b> — sum of auto-filled toll fees for the '
        'current day.',
    ]): out.append(x)

    out.append(h2('Filtering Events'))
    out.append(p('Six filters are available: From Date, To Date, Plate, '
                  'Event Type, Expressway, and a Clear button. Filters '
                  'apply immediately upon change. Use them to '
                  'investigate a specific transit or to audit a '
                  'reported missing toll fee.'))

    out.append(h2('Exporting to Excel'))
    out.append(p('Click <b>Export to Excel</b> to download all '
                  'currently filtered events as an .xlsx file. The '
                  'export preserves the filter state, so to export the '
                  'full log, click <b>Clear Filters</b> first.'))

    out.append(h2('Reconciling Auto-Filled Tolls'))
    out.append(pj(
        'Finance reconciles auto-filled tolls against physical '
        'receipts on a weekly basis. Any discrepancy greater than '
        'twenty pesos is investigated. Common causes of '
        'discrepancies are: a plate not mapped to Cartrack (no GPS '
        'evidence collected); a transit completed too quickly to be '
        'captured at the current polling cadence; or the plaza\'s GPS '
        'coordinates falling outside the actual booth location.'))

    # ── B.7 Truck Cycle Time ──────────────────────────────────────────
    out.append(h1('B.7 Truck Cycle Time'))
    out.append(pj(
        'The Truck Cycle Time module is the fleet manager\'s live '
        'situational-awareness view. It shows, for every active plate, '
        'where the truck is right now, what it\'s doing, and the full '
        'audit trail of every stop and movement during its current and '
        'past round trips.'))
    out.append(pj(
        'A <b>cycle</b> is one full round trip: the truck leaves home '
        '(BIG BEN SCM or any geofence with category=home), visits '
        'sites and toll plazas along the way, and returns to a home '
        'geofence. Cycles open the moment a truck exits a home '
        'geofence and close when it re-enters one. Multi-day cycles '
        'are supported.'))
    out.append(screenshot_placeholder(
        'Truck Cycle Time — KPI cards, idling chart, plate-status '
        'table with expandable rows', image='truck_cycle.png', height_cm=11))

    out.append(h2('KPI Cards'))
    for x in bullet_list([
        '<b>Open Cycles</b> — trucks currently away from home base.',
        '<b>Closed Today</b> — round trips that completed today.',
        '<b>Avg Cycle Time</b> — average round-trip duration over the '
        'past seven days.',
        '<b>Long Cycles</b> — round trips exceeding twenty-four hours '
        'over the past seven days.',
    ]): out.append(x)

    out.append(h2('Idling Rate Chart'))
    out.append(p('A horizontal bar chart ranking the top fifteen '
                  'trucks by overall idling percentage. Bars are '
                  'colour-coded: green (under 15 percent), amber '
                  '(15–30 percent), orange (30–50 percent), red '
                  '(above 50 percent). Excessive idling indicates '
                  'fuel waste or operational delays.'))

    out.append(h2('Filters'))
    out.append(p('Five filters are available: From Date, To Date, '
                  '<b>Truck Type</b>, Plate (cascades from truck type), '
                  'Cycle Length (Short, Standard, Long, Ongoing), and '
                  'Status (Open, Closed, All). Filters apply both to '
                  'the Plate Status table and to the cycle picker '
                  'inside an expanded row.'))

    # ── Plate Status table ─────────────────────────────────────────
    out.append(h2('Plate Status Table'))
    out.append(pj(
        'The page presents one row per active plate, not one row per '
        'cycle. Sorting is automatic: trucks with an open cycle '
        'appear at the top (longest elapsed first), and parked '
        'plates at the bottom (alphabetical, greyed out). At a '
        'glance the fleet manager can see exactly which trucks are '
        'on the road, how long they have been out, and where they '
        'last departed from.'))

    plate_cols = [
        ['Column', 'Description'],
        ['Plate',          'Body number / registration (e.g., DT15 / NHF9508).'],
        ['Status',         'Live status badge — DRIVING, IDLING, STOPPED, or OFF — colour-coded for quick scanning.'],
        ['Currently At',   'Geofence name if the truck is inside one, "In transit" if on the road, or a real-time amber "Stopped — Xm" badge with the address if the truck is in an ongoing ad-hoc stop.'],
        ['Last Departure', 'Time and location of the truck\'s most recent departure from a tracked location.'],
        ['Out For',        'How long the open cycle has been running. Highlights amber when > 24 hours.'],
        ['Stops',          'Count of real visits in the current open cycle (drive-bys excluded).'],
        ['Location',       'Reverse-geocoded address from Cartrack — useful for trucks in transit between geofences.'],
    ]
    out.append(std_table(plate_cols, col_widths=[3.5 * cm, 13 * cm]))

    out.append(h3('Click a row to expand'))
    out.append(pj(
        'Selecting any plate row reveals a panel below it with a '
        'chronological view of that plate\'s cycle history. Two '
        'controls appear:'))
    for x in bullet_list([
        '<b>Cycle picker chips</b> — one chip per cycle (open + closed) '
        'within the page\'s date filter range. The currently-open cycle '
        'is highlighted; closed cycles are grouped by date.',
        '<b>Audit trail timeline</b> — once a chip is picked, the '
        'panel renders the complete sequence of events for that cycle, '
        'in chronological order.',
    ]): out.append(x)

    out.append(h3('Audit trail event types'))
    audit_rows = [
        ['Icon',  'Kind',          'Source',     'Meaning'],
        ['🟢',     'DEPARTED',      'SiteVisit',   'Truck left a known geofence (cycle home base, customer, quarry, etc.).'],
        ['🔵',     'ARRIVED',       'SiteVisit',   'Truck entered a known geofence.'],
        ['⏸️',     'STOPPED',       'SiteVisit',   'Ad-hoc stop — truck stopped for ≥ N minutes outside any geofence. Address captured from Cartrack reverse-geocode.'],
        ['🛣️',     'PLAZA IN/OUT',  'CartrackEvent','Truck entered or exited a toll plaza geofence.'],
        ['💰',     'TOLL FILLED',   'CartrackEvent','GPS-detected toll fee computed (reference / Dashboard KPI — NOT written to the trip\'s Toll Fee field). See SOP-004.'],
    ]
    out.append(std_table(audit_rows, col_widths=[1 * cm, 3 * cm, 3 * cm, 9.5 * cm]))

    out.append(h2('Settings (Configurable Thresholds)'))
    out.append(pj(
        'A <b>Settings</b> button in the page toolbar opens a modal '
        'where dispatch operators can adjust the two operational '
        'thresholds without code changes:'))
    settings_rows = [
        ['Setting',                  'Default', 'Effect'],
        ['Minimum visit dwell',      '5 min',   'Geofence visits shorter than this are flagged is_drive_by=True and hidden from analytics. Toll plazas are exempt — see SOP-004.'],
        ['Stop detection threshold', '10 min',  'Truck stopping outside any geofence for at least this duration is logged as an ad-hoc stop SiteVisit (with address). Below the threshold, the stop is ignored.'],
    ]
    out.append(std_table(settings_rows, col_widths=[4.5 * cm, 2.5 * cm, 9 * cm]))
    out.append(p('Both values are stored in the AppSetting table. The '
                  'polling worker re-reads them on every iteration, so '
                  'admin changes apply within the next polling cycle. '
                  'Non-admin users see the settings as read-only.'))

    out.append(h2('Clear Logs (Admin Only)'))
    out.append(pj(
        'Within the Settings modal, an admin-only Danger Zone exposes '
        'a Clear Logs action. This deletes tracking data older than a '
        'chosen cutoff date — useful when wiping trial-period noise '
        'before going fully live, or for periodic retention pruning.'))
    out.append(h3('What gets cleared'))
    for x in bullet_list([
        '<b>SiteVisit</b> rows (geofence visits + ad-hoc stops)',
        '<b>TruckCycle</b> rows (round-trip records)',
        '<b>CartrackEvent</b> rows (plaza ENTER / EXIT / trip_closed events)',
    ]): out.append(x)
    out.append(h3('What is preserved'))
    for x in bullet_list([
        'All master data (plates, drivers, helpers, products, clients, dispatchers, truck types)',
        'All TripRecord rows (including manual toll_fee entries)',
        'All BreakdownLog rows',
        'All CartrackGeofence rows (the geofence cache)',
        'All user accounts and AppSetting values',
    ]): out.append(x)
    out.append(callout(
        'Three independent safety gates',
        'The Clear Logs action requires: (1) admin role at the API '
        'layer (non-admins get HTTP 403), (2) a cutoff date — full '
        'wipes are not allowed; only records older than the cutoff are '
        'deleted, and (3) the exact text <b>CLEAR</b> typed into a '
        'confirmation field. The submit button stays disabled until '
        'all three conditions are met, plus one final browser '
        'confirm() before the request fires.',
        kind='warn'))

    out.append(h2('Manual Geofences (Coord-Based Workaround)'))
    out.append(pj(
        'Most geofences are managed in Cartrack and synced into the '
        'application via the <b>Sync Geofences</b> button. If a real '
        'Cartrack geofence ever becomes invisible to the API (e.g., a '
        'permission filter or pagination quirk), administrators can '
        'add an entry to <font face="Courier">manual_geofences.json</font> '
        'at the project root. Each entry has a name, category, '
        'lat/lng, and radius in metres. The polling worker computes '
        'haversine distance from each truck\'s GPS to every manual '
        'geofence on every poll, and treats matches as if they came '
        'from Cartrack itself — same cycle and site-visit behaviour.'))
    out.append(p('Categories supported: home, customer, quarry, fuel, '
                  'toll, operations, other. Set category to "home" to '
                  'make the geofence behave as a second home base for '
                  'cycle open/close detection.'))

    out.append(h2('Cycle Categories'))
    cyc_rows = [
        ['Category', 'Duration', 'Typical Pattern'],
        ['Short',     'Under 12 hours',  'Single round trip within a single business day.'],
        ['Standard',  '12 – 24 hours',   'Long single-day route, or a quick overnight.'],
        ['Long',      'Over 24 hours',   'Multi-day journey (e.g., Cebu container runs).'],
        ['Ongoing',   'Not yet closed',  'Cycle still open at the time the report is generated.'],
    ]
    out.append(std_table(cyc_rows, col_widths=[3 * cm, 4 * cm, 9.5 * cm]))

    out.append(h2('Syncing Geofences'))
    out.append(p('Click <b>Sync Geofences</b> in the page toolbar to '
                  'pull the latest geofence list from Cartrack. New '
                  'geofences created in Cartrack are not visible to the '
                  'system until this sync runs. The sync is safe to '
                  'run on demand.'))

    # ── B.8 Reports ───────────────────────────────────────────────────
    out.append(h1('B.8 Reports'))
    out.append(pj(
        'The Reports module produces summarised views over '
        'configurable date ranges. Reports are intended for '
        'management review and finance reconciliation rather than '
        'live operations.'))
    out.append(screenshot_placeholder('Reports page — date range, '
                                         'aggregate KPIs, trip table',
                                         image='reports.png', height_cm=11))

    out.append(h2('Configurable Range'))
    out.append(p('The date selector at the top of the page allows any '
                  'continuous range. Common selections include: today, '
                  'yesterday, this week, last week, this month, and '
                  'last month.'))

    out.append(h2('Exports'))
    out.append(p('Click <b>Export to Excel</b> to download the full '
                  'trip set as an .xlsx file. Alternatively, click '
                  '<b>Sync to Google Sheets</b> to push the data into '
                  'the configured shared sheet for finance.'))

    # ── B.9 Admin / Settings ──────────────────────────────────────────
    out.append(h1('B.9 Administration and Settings'))
    out.append(pj(
        'The Admin module is restricted by convention to the IT '
        'Administrator and the Management Representative. It provides '
        'access to user accounts, environment variables, integration '
        'configuration, and database maintenance utilities.'))

    out.append(h2('User Account Management'))
    out.append(p('Create, deactivate, and reset passwords for '
                  'application user accounts. Each user has a unique '
                  'username and a hashed password; the system does not '
                  'store plaintext passwords.'))

    out.append(h2('Environment Variables'))
    out.append(p('Cartrack credentials, Google Sheets webhook URL, '
                  'and other secrets are stored as environment '
                  'variables on the PythonAnywhere host. They are not '
                  'displayed in the application user interface. The '
                  'IT Administrator manages them via the '
                  'PythonAnywhere Web tab.'))

    out.append(h2('Database Backup'))
    out.append(p('A scripted daily backup of the SQLite database is '
                  'recommended. See SOP-005 (Data Backup and User '
                  'Access Management) for the full procedure.'))

    return out
