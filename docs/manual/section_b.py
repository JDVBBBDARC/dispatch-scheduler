"""Section B — User Manual (8 modules)."""
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
        'eight modules in the Dispatch Scheduler. Each subsection follows '
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
    out.append(pj(
        'The filter bar at the top scopes every KPI and chart: Truck '
        'type and Status apply instantly on selection, while the From '
        'and To dates apply only when the <b>Apply</b> button is '
        'clicked — so picking the first date no longer reloads the '
        'page before the second can be set.'))
    out.append(screenshot_placeholder(
        'Dashboard overview — KPI cards, fleet utilisation, breakdown chart, '
        'truck cycle widget', image='dashboard.png', height_cm=11))

    out.append(h2('KPI Cards'))
    out.append(p('Eight headline indicators sit at the top of the page, '
                  'all computed over the selected date range. Each card '
                  'is clickable: most open a drill-down dialog showing '
                  'the underlying trips; the GPS Toll card jumps to the '
                  'Toll Log module (B.6).'))
    kpi_rows = [
        ['KPI', 'Definition'],
        ['Total Trips',     'Count of trips whose Wave date falls in the selected range.'],
        ['Delivered',       'Trips with status = Delivered, with % of total.'],
        ['In Transit',      'Trips currently on the road.'],
        ['Toll Fee',        'Sum of toll_fee across non-cancelled trips. Recorded manually by the dispatcher from the physical receipt or RFID statement — the billing source of truth.'],
        ['GPS Toll',        'Sum of GPS-detected toll fees from the Toll Log (B.6) over the same range. Independent of the manual figure; used for reconciliation, never for billing.'],
        ['Breakdown Hours', 'Total completed job-order hours from the Breakdown module in the range. Click for J.O. details.'],
        ['Pending',         'Trips not yet started.'],
        ['Canceled',        'Cancelled trips (excluded from toll sums).'],
    ]
    out.append(std_table(kpi_rows, col_widths=[3.3 * cm, 13.2 * cm]))

    out.append(h2('Trend Deltas (vs Previous Period)'))
    out.append(pj(
        'Below each KPI value a small arrow badge compares the figure '
        'to the previous period of equal length — a fourteen-day range '
        'is compared against the fourteen days immediately before it. '
        'The colour reflects meaning, not merely direction: an '
        'increase in Total Trips or Delivered shows green (good), an '
        'increase in Breakdown Hours, Pending, or Canceled shows red '
        '(needs attention), and toll figures show neutral grey. The '
        'badge is hidden when the previous period had no data to '
        'compare against. Hovering over the badge shows the exact '
        'comparison window.'))

    out.append(h2('Fleet Utilisation Chart'))
    out.append(pj(
        'The horizontal bar chart shows each truck type\'s percentage '
        'of daily target points achieved. Each truck type has a '
        'per-leg point value (typically 1.0, or 0.5 for ten-wheelers) '
        'and a daily target (typically 1.5, or 4.0 for ten-wheelers). '
        'Bars are colour-coded green (≥100%), amber (70–99%), and red '
        '(below 70%). The <b>OT (Others)</b> category is excluded '
        'from this chart: it holds the hustling/hauling runs, which '
        'operations deliberately keeps out of utilisation.'))

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
        'the home geofence), Closed Today, Average Cycle Hours over the past '
        'seven days, and Long Cycles (those exceeding twenty-four '
        'hours). Click the <b>Open Truck Cycle Time</b> button to '
        'jump to the dedicated cycle-time analytics page.'))

    out.append(h2('Customising the Layout (Drag and Resize)'))
    out.append(pj(
        'Every chart panel below the KPI row can be rearranged and '
        'resized to suit the user\'s workflow:'))
    for x in bullet_list([
        '<b>Move a chart</b> — drag it by its title bar (a grip icon '
        'appears at the left of the header) and drop it in the desired '
        'position. The other panels reflow automatically.',
        '<b>Resize height</b> — hover over the chart and drag the '
        'horizontal bar that appears along its bottom edge.',
        '<b>Resize width</b> — drag the vertical bar at the panel\'s '
        'right edge; width can be set between a quarter and the full '
        'row.',
        '<b>Reset layout</b> — a Reset button appears at the top of '
        'the grid once anything differs from the default; clicking it '
        'restores the original order and sizes.',
    ]): out.append(x)
    out.append(callout(
        'Per-Browser Setting',
        'The saved layout lives in the browser (localStorage), not in '
        'the user account. Arranging the dashboard on one computer '
        'does not carry the arrangement to another machine, and '
        'clearing browser data resets it.',
        kind='info'))

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
        'Enter the Toll Fee from the physical receipt or RFID '
        'statement once the trip is complete.',
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

    out.append(h2('Copying and Pasting Rows (Excel-style)'))
    out.append(pj(
        'Beyond the single-row copy icon, whole rows can be selected '
        'and pasted like spreadsheet cells — including into another '
        'wave, another truck-type tab, or another <b>day</b>:'))
    for x in bullet_list([
        '<b>Select</b> — click a row\'s number to select it. '
        'Ctrl+click adds or removes rows; Shift+click selects a '
        'range; Esc clears the selection. Selected rows are '
        'highlighted with a maroon edge.',
        '<b>Copy (Ctrl+C)</b> — copies the selected rows\' '
        'assignments: trip type, driver, helper, plate, product, '
        'client, and dispatcher.',
        '<b>Paste (Ctrl+V or the Paste button)</b> — inserts the '
        'copied rows into the open wave as fresh <i>Pending</i> '
        'trips. RS/PO/DR numbers and volume are left blank on '
        'purpose: reference numbers belong to the new run.',
    ]): out.append(x)
    out.append(callout(
        'Repeating daily patterns',
        'The copied rows survive page navigation. Copy Monday\'s '
        'rows, press Next to open Tuesday, and paste — the whole '
        'pattern transfers without re-encoding. The clipboard is '
        'per-browser, like the dashboard layout.',
        kind='ok'))

    out.append(h2('Adjusting Column Widths'))
    out.append(pj(
        'Drag the right edge of any column header to resize it, '
        'exactly as in a spreadsheet. The width applies to the same '
        'column in every wave table so the grids stay aligned, and it '
        'is remembered by the browser. Double-click a column edge to '
        'reset that column to its default width.'))

    out.append(h2('Updating Trip Status'))
    out.append(p('The Status badge cycles through the operational '
                  'states when clicked: <b>Pending → In Transit → '
                  'Delivered → Canceled</b>.'))
    status_rows = [
        ['Status',     'Meaning', 'When to set'],
        ['Pending',    'Trip planned but not yet started.',          'At trip creation, or when reverting an incorrect status.'],
        ['In Transit', 'Truck is en route to the customer.',          'When the truck departs the loading point.'],
        ['Delivered',  'Cargo has been received and signed for.',     'On confirmation from the driver / customer.'],
        ['Canceled',   'Trip was assigned but did not run.',          'When a customer cancels, or weather / breakdown prevents execution.'],
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

    out.append(h2('Importing the Monthly Monitoring Workbook'))
    out.append(pj(
        'The <b>Import Excel</b> button (top-right of the Schedule '
        'page) creates an entire month of waves and trips from the '
        '"Daily Sales and Logistics Materials Monitoring" workbook. '
        'The importer reads four tabs — <b>2.0 Data Input, 2.1 '
        'Data_Rental, 2.2 Data_CPS,</b> and <b>6.0 Waste Input</b> — '
        'and finds the columns by their headers, so minor layout '
        'changes between months do not break it.'))
    for x in numbered_list([
        'Click <b>Import Excel</b> and choose the workbook file.',
        'Click <b>Preview</b> — nothing is written yet. Review the '
        'counts: trips to create per date, duplicates skipped, rows '
        'without a plate, and every NEW client / product / driver / '
        'helper / plate the import would add to Master Data.',
        'Click <b>Import Now</b>. The page then opens the first '
        'imported date so the result is immediately visible.',
    ]): out.append(x)

    out.append(p('<b>Rules the importer applies automatically:</b>'))
    import_rules = [
        ['Rule', 'Behaviour'],
        ['Waves',        'A plate\'s 1st trip of the day lands in Wave 1, its 2nd in Wave 2, and so on — counted separately per tab, so hauling runs never push a plate\'s deliveries into later waves.'],
        ['Trip type',    'Clients containing RMC / RMP / Stockpile import as Back Load; all other clients as Front Load. Waste-input rows: Eco Protect is Front Load, every other destination Back Load.'],
        ['Hustling',     'A 12W or 22WD dump truck serving RMC / Asphalt Plant / CPS is a hauling ("hustling") run: filed under the OT (Others) tab with trip type Hustling, and excluded from Fleet Utilisation.'],
        ['Statuses',     'Completed → Delivered, Cancelled → Canceled, blank → Pending. Rows whose date cell holds text (e.g. "Cancelled") are skipped, never guessed.'],
        ['Master data',  'Unknown names are auto-created. Name variants match automatically ("Arnel Eusebio" = "A. Eusebio"), so spelling differences do not create duplicates. New plates default to truck type OT — recategorise them in Master Data afterwards.'],
        ['Duplicates',   'Re-uploading the same (or an updated) workbook never doubles trips: rows are skipped when their DR No. already exists on that date or an identical trip sits in the same wave. Upload the growing file weekly, safely.'],
    ]
    out.append(std_table(import_rules, col_widths=[2.8 * cm, 13.7 * cm]))

    out.append(h2('Reverting an Import'))
    out.append(pj(
        'Every import is journaled. Re-opening the Import dialog shows '
        'the last import with a <b>Revert this import</b> button: it '
        'removes exactly the trips that import created, any waves left '
        'empty by that removal, and any auto-created master-data '
        'records nothing else uses. Trips a dispatcher has edited '
        'since the import are kept. Typical use: revert, fix the '
        'workbook, upload again.'))

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
        'Breakdown module — incident table populated by FixFlo sync',
        image='breakdown.png', height_cm=10))

    out.append(h2('FixFlo Integration'))
    out.append(pj(
        'The Breakdown module does <b>not</b> use manual entry. All '
        'records are sourced directly from <b>FixFlo</b>, the workshop '
        'management system used by the mechanics. When a mechanic logs '
        'a repair request in FixFlo, the Dispatch Scheduler pulls the '
        'job order, derives the breakdown record (plate, start time, '
        'status, description, mechanic, resolution), and inserts or '
        'updates the corresponding row on the Breakdown page.'))
    out.append(pj(
        'A background sync runs automatically; users can also trigger '
        'an on-demand pull with the <b>Sync from FixFlo</b> button at '
        'the top of the page when a freshly-logged job order needs to '
        'appear immediately.'))

    out.append(h2('What Gets Synced'))
    sync_rows = [
        ['Field', 'Source in FixFlo'],
        ['Plate',         'Job order vehicle'],
        ['Started At',    'Job order start timestamp (authoritative — overrides any other date)'],
        ['Ended At',      'Job order completion timestamp (cleared automatically if status reverts)'],
        ['Status',        'Derived from the latest FixFlo status log entry'],
        ['Description',   'Built from FixFlo JO reference codes and request titles'],
        ['Remarks',       'Mechanic names + the latest status log line'],
        ['Resolution',    'Resolution notes captured by the mechanic on close-out'],
        ['Operator',      'The "Operator Name" on the job order — the driver associated with the incident. Feeds the Breakdowns-by-Driver chart.'],
        ['Equipment',     'The original FixFlo equipment name (e.g. "Howo Trailer Dump #14"). Shown when the job order could not be matched to a registered fleet plate — typically trailers and other non-plate assets.'],
    ]
    out.append(std_table(sync_rows, col_widths=[4.5 * cm, 12 * cm]))
    out.append(p(
        'Rows whose equipment is not registered in Master Data show the '
        'FixFlo equipment name in small italic text below the (empty) '
        'plate selector, so the record still identifies what was '
        'repaired.'))

    out.append(h2('Filtering'))
    out.append(pj(
        'A filter bar sits between the KPI cards and the charts. Four '
        'dropdowns — <b>Year</b>, <b>Month</b>, <b>Status</b>, and '
        '<b>Plate</b> (grouped by truck type) — apply immediately on '
        'change and drive everything below them: the charts, the '
        'breakdown table, and the bar-click detail modal all show the '
        'same filtered window. Equipment that is not registered as a '
        'fleet plate cannot be reached by the Plate dropdown — use its '
        'bar on the Breakdowns-by-Plate chart instead (see below).'))

    out.append(h2('Breakdown Analytics (Bar Charts)'))
    out.append(pj(
        'Two ranked bar charts summarise the filtered window, drawn '
        'one below the other between the filter bar and the table.'))
    chart_rows = [
        ['Chart', 'What it shows'],
        ['Breakdowns by Plate',
         'One bar per unit, ranked by breakdown count. Maroon bars are '
         'registered fleet plates (the worst offender is drawn in a '
         'darker shade). Grey bars are FixFlo equipment with no '
         'matching plate in Master Data — typically trailers — so '
         'trailer incidents stay visible in the ranking without being '
         'mistaken for fleet plates.'],
        ['Breakdowns by Driver',
         'One bar per driver (slate blue), counted from the job '
         'order\'s Operator Name. Spelling variants of the same '
         'person — e.g. "JIM LAYAG" and "J.LAYAG", or one-letter '
         'surname typos — are merged automatically into a single bar; '
         'hovering shows the list of merged spellings so any wrong '
         'merge is visible at a glance. Records with no operator '
         'listed are excluded.'],
    ]
    out.append(std_table(chart_rows, col_widths=[4.5 * cm, 12 * cm]))

    out.append(h2('Drilling into a Bar (Job-Order Modal)'))
    for x in numbered_list([
        'Click any bar on either chart.',
        'A dialog opens listing every job order behind that bar — '
        'date, JO reference, description, status, start and end '
        'times, repair hours, operator, and remarks.',
        'The list respects the current Year / Month / Status filters, '
        'so the modal always matches the chart you clicked.',
        'Where FixFlo provides a link, the JO reference opens the '
        'original job order in FixFlo in a new tab.',
    ]): out.append(x)
    out.append(callout(
        'Why this matters for trailers',
        'Equipment that is not in Master Data (grey bars) cannot be '
        'selected in the Plate filter dropdown. The bar-click modal is '
        'the way to review a trailer\'s repair history — click its '
        'grey bar and the full job-order list appears.',
        kind='note'))

    out.append(h2('Breakdown Statuses'))
    bd_rows = [
        ['Status',       'Meaning'],
        ['Under Repair', 'FixFlo job order is open and in progress. Plate is unavailable for dispatch.'],
        ['Fixed',        'FixFlo job order is closed/completed. Plate is back in service.'],
        ['Standby',      'Plate is operational but held out of service (e.g., waiting for parts, scheduled inspection).'],
    ]
    out.append(std_table(bd_rows, col_widths=[3.5 * cm, 13 * cm]))
    out.append(callout(
        'Single Source of Truth',
        'All repair data originates in FixFlo. The Dispatch Scheduler '
        'is a read-only mirror — fields are not editable on the '
        'Breakdown page. To correct an incident, the mechanic edits '
        'the job order in FixFlo and the next sync pulls the '
        'correction. See SOP-003 (Breakdown Reporting).',
        kind='note'))

    # ── B.5 Toll Calculator ───────────────────────────────────────────
    out.append(h1('B.5 Toll Calculator'))
    out.append(pj(
        'The Toll Calculator computes the expected toll fee between '
        'any two plazas on any supported expressway. It is a '
        'standalone reference tool the dispatch team can use to '
        'estimate trip costs in advance, or to confirm the expected '
        'fee against a physical receipt.'))
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
        'The Toll Log records toll-plaza transits detected '
        'automatically from GPS. Geofences drawn around the physical '
        'toll booths in the Cartrack platform (96 plazas, positioned '
        'at booth level) report when a mapped truck passes through; '
        'the system pairs an entry plaza with the exit plaza and '
        'computes the expected fee from the same rate matrix the Toll '
        'Calculator uses.'))
    out.append(screenshot_placeholder(
        'Toll Log — KPI cards, filters, and the paired entry→exit '
        'trips table', image='toll_log.png', height_cm=10))

    out.append(h2('What the Page Shows'))
    for x in bullet_list([
        '<b>KPI cards</b> — Plaza Enters and Plaza Exits over the '
        'last seven days, Trips Auto-Filled, and Toll Fees Today.',
        '<b>Toll Trips view</b> (default) — one row per completed '
        'transit: date/time, plate, entry plaza, exit plaza, the '
        'expressway(s) traversed, and the computed fee. Routes that '
        'span more than one expressway list the actual chain, e.g. '
        '<i>NLEX_SCTEX + NLEX_Connector</i>.',
        '<b>Audit Detail view</b> — the raw enter/exit event stream '
        'behind the paired trips, for verifying an individual '
        'crossing.',
        '<b>Filters</b> — date range, plate, and expressway; '
        '<b>Export to Excel</b> respects the active filters.',
    ]): out.append(x)

    out.append(h2('How a Trip Is Assembled'))
    for x in numbered_list([
        'The truck enters any toll geofence — this opens a pending '
        'transit and records the entry plaza.',
        'Passing further plazas updates the running exit candidate.',
        'When the truck has been clear of toll geofences for a '
        'configured idle window (45 minutes), the transit closes: '
        'entry and latest plaza become the pair, and the fee is '
        'computed for the plate\'s vehicle class (Class 1, 2, or 3 '
        'from Master Data).',
        'A truck that touches only one plaza (e.g., a U-turn before '
        'the barrier) is discarded — a single touch is not a transit.',
    ]): out.append(x)

    out.append(callout(
        'GPS Toll Is for Reconciliation, Not Billing',
        'The GPS-detected fee is never written into the Schedule\'s '
        'toll_fee field. Manual encoding from physical receipts and '
        'RFID statements remains the billing source of truth. The '
        'value of the Toll Log is comparison: a GPS-detected transit '
        'with no matching receipt (or the reverse) surfaces missed '
        'encoding, toll exemptions, or RFID glitches. See SOP-004.',
        kind='warn'))

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
        '(the home geofence or any geofence with category=home), visits '
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
        ['🛣️',     'PLAZA IN/OUT',  'CartrackEvent','Truck entered or exited a toll plaza geofence (for situational awareness; not used to bill).'],
    ]
    out.append(std_table(audit_rows, col_widths=[1 * cm, 3 * cm, 3 * cm, 9.5 * cm]))

    out.append(h2('Settings (Configurable Thresholds)'))
    out.append(pj(
        'A <b>Settings</b> button in the page toolbar opens a modal '
        'where dispatch operators can adjust the two operational '
        'thresholds without code changes:'))
    settings_rows = [
        ['Setting',                  'Default', 'Effect'],
        ['Minimum visit dwell',      '5 min',   'Geofence visits shorter than this are flagged is_drive_by=True and hidden from analytics. Toll plazas are exempt from this filter.'],
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
        'Administrator and the Operations Manager. It provides access '
        'to user accounts, environment variables, integration '
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
