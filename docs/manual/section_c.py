"""Section C — Standard Operating Procedures (SOPs).

Six procedures in a uniform format: Purpose, Scope, Responsibilities,
Procedure, Records, Frequency, References."""
from reportlab.platypus import PageBreak
from reportlab.lib.units import cm
from helpers import (h_section, h1, h2, h3, p, pj, lead, sp, code,
                      bullet_list, numbered_list, std_table, callout,
                      sop_box, S)


def section_c():
    out = []
    out.append(PageBreak())
    out.append(h_section('Section C — Standard Operating Procedures'))
    out.append(lead(
        'This section documents the six core Standard Operating '
        'Procedures (SOPs) that govern the daily use of the Dispatch '
        'Scheduler System. Each SOP follows a uniform format and is '
        'identified by a unique code (SOP-XXX) referenced throughout '
        'this manual.'))

    out.append(callout(
        'Mandatory Reading',
        'All personnel who interact with the Dispatch Scheduler System '
        'should read the SOPs applicable to their role before operating '
        'the system unsupervised. Onboarding sign-off is recorded by '
        'the team lead during the first-week orientation.',
        kind='note'))

    # ── SOP-001: Daily Dispatch ────────────────────────────────────────
    out += sop_box(
        sop_id='001',
        title='Daily Dispatch Planning and Execution',
        purpose=(
            'To ensure that every operational day begins with a complete, '
            'approved, and executable trip plan, and that the plan is '
            'updated in the system promptly as conditions change.'),
        scope=(
            'Applies to all weekday and weekend dispatch operations '
            'conducted using the Dispatch Scheduler. Covers the period '
            'from the previous day\'s 6:00 PM planning meeting through '
            'the current day\'s end-of-day reconciliation.'),
        responsibilities=(
            '<b>Dispatcher</b> — builds the plan, assigns trips, updates '
            'statuses throughout the day.<br/>'
            '<b>Dispatch Supervisor</b> — reviews and approves the plan '
            'before 7:00 AM; intervenes on exceptions.<br/>'
            '<b>Operations Manager</b> — final accountability for plan '
            'completeness and execution.'),
        procedure=[
            'Receive confirmed customer purchase orders and trip '
            'requests from the previous day\'s planning meeting.',
            'Open the Dispatch Scheduler and navigate to the <b>Schedule</b> '
            'module for the current operational date.',
            'For each truck type, create the required Waves and add one '
            'trip row per planned delivery or pickup. Required fields: '
            'Driver, Helper, Plate, Product, Client, Dispatcher.',
            'Cross-check that each assigned Plate is not currently '
            'recorded as Under Repair in the Breakdown module. If it is, '
            'reassign to an available Plate.',
            'Cross-check that each assigned Driver is qualified for the '
            'Plate\'s Truck Type. Master Data enforces this implicitly via '
            'the Driver-Type relationship; resolve any mismatch before '
            'proceeding.',
            'Enter the expected toll fee per trip using the Toll '
            'Calculator. Trips that auto-fill from GPS will overwrite '
            'this figure later.',
            'Submit the day\'s plan for Dispatch Supervisor review.',
            'On supervisor approval, set the trip statuses to <b>Pending</b> '
            '(default) — no further action required until dispatch.',
            'As trucks depart, update trip status to <b>Loading</b> upon '
            'arrival at loading point, then <b>In Transit</b> on departure.',
            'On delivery confirmation, update status to <b>Delivered</b> '
            'and verify the toll_fee has populated. If still zero, '
            'investigate (see SOP-004).',
        ],
        records=(
            'TripRecord rows in the database; Wave records; status '
            'change timestamps (audit log); auto-fill toll evidence '
            '(CartrackEvent + SiteVisit rows).'),
        frequency='Daily — every operational day, including weekends.',
        references=(
            'SOP-002 End-of-Day Reconciliation<br/>'
            'SOP-004 Toll Documentation'),
    )

    # ── SOP-002: End-of-Day Reconciliation ─────────────────────────────
    out += sop_box(
        sop_id='002',
        title='End-of-Day Reconciliation',
        purpose=(
            'To ensure that every trip planned for the operational day '
            'has been closed out with an accurate final status, that all '
            'toll fees have been verified, and that any unresolved '
            'exceptions are documented and escalated before the daily '
            'records are considered final.'),
        scope=(
            'Performed at the end of each operational day, after all '
            'trucks have either returned to the home base or been '
            'confirmed as multi-day cycles in progress.'),
        responsibilities=(
            '<b>Dispatcher (closing shift)</b> — performs the '
            'reconciliation.<br/>'
            '<b>Dispatch Supervisor</b> — reviews and signs off.<br/>'
            '<b>Finance Officer</b> — receives the closed-out totals for '
            'next-day reconciliation.'),
        procedure=[
            'Navigate to the <b>Schedule</b> module for the current date.',
            'Iterate through each truck-type tab in turn.',
            'For each trip row, confirm the status is one of: '
            '<b>Delivered</b>, <b>Cancelled</b>. Any trip still in '
            '<b>Pending</b>, <b>Loading</b>, or <b>In Transit</b> is an '
            'exception.',
            'For each exception, contact the assigned driver or '
            'dispatcher to determine the actual outcome. Update the '
            'status accordingly.',
            'Open the <b>Toll Log</b> page and filter to the current date.',
            'For each Delivered trip, verify a corresponding toll '
            'auto-fill is present, or that the manual toll entry matches '
            'the physical receipt.',
            'For trips with toll_fee = 0 that should have a toll, '
            'manually enter the figure from the receipt. Add a note in '
            'the trip\'s Notes field indicating "Manual entry — no GPS '
            'evidence".',
            'Open the <b>Dashboard</b> and confirm the Trips Today, '
            'Delivered, and Total Toll KPIs reflect the expected '
            'figures.',
            'Click <b>Sync to Google Sheets</b> on the Reports page to '
            'push the day\'s data for Finance.',
            'Notify the Dispatch Supervisor that reconciliation is '
            'complete.',
        ],
        records=(
            'Final TripRecord statuses; manually entered toll fees with '
            'Notes; Google Sheets sync timestamp; Supervisor sign-off '
            '(verbal or written log).'),
        frequency='Daily — within two hours of the last truck '
                  'returning to home base.',
        references=(
            'SOP-001 Daily Dispatch<br/>'
            'SOP-004 Toll Documentation'),
    )

    # ── SOP-003: Breakdown Reporting ───────────────────────────────────
    out += sop_box(
        sop_id='003',
        title='Breakdown Reporting and Plate Availability Management',
        purpose=(
            'To ensure that every mechanical, electrical, or accident-'
            'related event that takes a plate out of service is '
            'recorded promptly, the affected plate is removed from '
            'dispatch availability, and the operational impact is '
            'communicated to all relevant parties.'),
        scope=(
            'Applies to any event that prevents a plate from completing '
            'its planned trip or being assigned to subsequent trips. '
            'Includes scheduled maintenance, unplanned breakdowns, '
            'accidents, and standby holds.'),
        responsibilities=(
            '<b>Driver</b> — reports the event immediately to the '
            'Dispatcher.<br/>'
            '<b>Dispatcher</b> — opens a Breakdown record in the system '
            'within thirty minutes of notification.<br/>'
            '<b>Fleet Manager</b> — assigns the plate to a mechanic, '
            'tracks repair progress, updates the resolution.'),
        procedure=[
            'Upon driver notification of a breakdown, record the '
            'time, location, and reported symptoms.',
            'Open the <b>Breakdown</b> module in the Dispatch '
            'Scheduler.',
            'Click <b>+ Log Breakdown</b> and complete the form: '
            'Plate, Start Date / Time, Status = <b>Under Repair</b>, '
            'Description (driver\'s reported symptoms).',
            'Save the breakdown record. The plate is now flagged as '
            'unavailable in dispatch dropdowns.',
            'Reassign the affected trip\'s Plate field to an '
            'available plate of the same truck type. If none is '
            'available, escalate to the Dispatch Supervisor.',
            'Notify the Fleet Manager via Viber or radio for '
            'recovery / repair dispatch.',
            'On receipt of repair confirmation from the mechanic, '
            're-open the breakdown record and set Status = <b>Fixed</b>, '
            'enter the End Date / Time, and add the resolution '
            'description.',
            'Confirm the plate is back in the dispatch pool for the '
            'next operational day.',
        ],
        records=(
            'BreakdownLog rows in the database; total downtime '
            'calculated automatically; Fleet Manager\'s mechanic '
            'communication log.'),
        frequency='Event-driven — within thirty minutes of any '
                  'service-affecting incident.',
        references=(
            'SOP-001 Daily Dispatch'),
    )

    # ── SOP-004: Toll Documentation ────────────────────────────────────
    out += sop_box(
        sop_id='004',
        title='Toll Documentation and Reconciliation',
        purpose=(
            'To ensure that every toll fee incurred by the fleet is '
            'recorded accurately and that the manual entries on trip '
            'records (the billing source of truth) reconcile with the '
            'physical evidence (toll receipts, RFID statements) and '
            'with the system\'s GPS-detected toll figures (reference).'),
        scope=(
            'All trips that traverse a Philippine expressway with a toll '
            'plaza. Excludes purely intra-city trips that incur no toll.'),
        responsibilities=(
            '<b>Dispatcher</b> — manually records the toll_fee on each '
            'trip from the physical receipt at end of trip.<br/>'
            '<b>Finance Officer</b> — reconciles weekly against the '
            'GPS Toll Dashboard KPI, RFID statements, and physical '
            'receipts.<br/>'
            '<b>Fleet Manager</b> — investigates any reconciliation '
            'discrepancy greater than twenty pesos.'),
        procedure=[
            'At end of trip, the dispatcher collects the physical '
            'toll receipt from the driver and enters the toll fee '
            'directly into the trip\'s Toll Fee field on the Schedule '
            'page. This is the <b>sole source of truth</b> for '
            'Finance billing. The polling worker does NOT modify '
            'this field.',
            'Throughout the day, the GPS polling worker detects '
            'plaza transits and computes the toll fee from the rate '
            'matrix. These figures are logged as CartrackEvent rows '
            'and aggregated into the Dashboard\'s <b>GPS Toll</b> '
            'KPI card. They are <b>reference / audit only</b> — they '
            'do not overwrite the dispatcher\'s manual entry.',
            'At end-of-day reconciliation (SOP-002), the dispatch '
            'supervisor cross-checks the day\'s Toll Fee total '
            '(manual) against the GPS Toll figure on the Dashboard. '
            'A small variance is expected; large gaps trigger '
            'investigation via the Toll Log page.',
            'On a weekly cadence (every Monday), Finance opens the '
            '<b>Toll Log</b> module, filters to the prior week, and '
            'exports to Excel.',
            'Finance produces a three-way reconciliation: '
            'TripRecord.toll_fee totals (manual), CartrackEvent '
            'totals (GPS), and RFID/receipt totals (physical). '
            'Discrepancies above twenty pesos per trip are flagged.',
            'Resolution of each discrepancy is recorded in the '
            'trip\'s Notes field and signed off by the Fleet Manager. '
            'Common causes: a toll exemption, a missed plaza '
            '(hidden geofence — see Manual Geofences in B.7), or a '
            'receipt typo.',
        ],
        records=(
            'TripRecord.toll_fee values (manual, the billing record); '
            'CartrackEvent rows with toll_fee + plaza pair (GPS '
            'reference); weekly reconciliation Excel exports; '
            'physical receipts (paper file).'),
        frequency='Per trip (manual entry at end of trip); end-of-day '
                  '(per SOP-002); weekly (Finance reconciliation, '
                  'every Monday).',
        references=(
            'SOP-001 Daily Dispatch<br/>'
            'SOP-002 End-of-Day Reconciliation<br/>'
            'Manual v1.1 — Toll auto-fill decoupling change'
            'resources)'),
    )

    # ── SOP-005: Data Backup & User Access ────────────────────────────
    out += sop_box(
        sop_id='005',
        title='Data Backup and User Access Management',
        purpose=(
            'To protect the integrity and availability of the '
            'operational records held in the Dispatch Scheduler '
            'database, and to ensure that user access is granted, '
            'maintained, and revoked in line with the principle of '
            'least privilege.'),
        scope=(
            'Applies to the SQLite database file, the application '
            'codebase, all environment variables, and every user '
            'account on the system.'),
        responsibilities=(
            '<b>IT Administrator</b> — performs backups, manages user '
            'accounts, holds the recovery credentials.<br/>'
            '<b>Operations Manager</b> — initiates account requests and '
            'revocations.<br/>'
            '<b>Operations Manager</b> — reviews active accounts on a '
            'quarterly cadence and confirms each is still required.'),
        procedure=[
            '<b>Backups.</b> A daily scheduled task on PythonAnywhere '
            'copies the SQLite database to a date-stamped file in a '
            'backups directory. The seven most recent daily backups are '
            'retained.',
            '<b>Off-site copy.</b> Each Friday, the IT Administrator '
            'downloads the latest daily backup to a designated '
            'encrypted external storage location.',
            '<b>Restore drill.</b> Once per quarter, the IT '
            'Administrator restores the most recent backup to a '
            'staging environment and verifies the database opens '
            'cleanly with no integrity errors.',
            '<b>Account request.</b> The Operations Manager sends a '
            'written request to the IT Administrator naming the new '
            'user and their role.',
            '<b>Account creation.</b> The IT Administrator creates the '
            'account with a randomly generated initial password, '
            'communicated to the new user out-of-band. The user is '
            'required to change the password on first login.',
            '<b>Periodic review.</b> The Operations Manager reviews the '
            'active user list every quarter and confirms each account is '
            'still required.',
            '<b>Account revocation.</b> On notification of staff '
            'separation, the IT Administrator deactivates the account '
            'within one business day. Account data is retained for '
            'audit purposes; the account is not deleted.',
        ],
        records=(
            'Daily backup files (date-stamped); restore-drill log; '
            'account creation and revocation log; quarterly access '
            'review minutes.'),
        frequency='Daily (backup); weekly (off-site copy); quarterly '
                  '(restore drill, access review); event-driven '
                  '(account creation, revocation).',
        references=(
            'SOP-001 Daily Dispatch (account requests originate from '
            'the dispatch chain)'),
    )

    # ── SOP-006: Cycle Time Monitoring ─────────────────────────────────
    out += sop_box(
        sop_id='006',
        title='Cycle Time and Idling Rate Monitoring',
        purpose=(
            'To use the GPS-driven Truck Cycle Time analytics to '
            'identify operational inefficiencies, address chronic '
            'idling, and surface long cycles that may indicate '
            'underlying problems with routing, customer wait times, or '
            'vehicle reliability.'),
        scope=(
            'Performed weekly on the consolidated cycle-time data for '
            'the prior calendar week. Covers all plates that completed '
            'at least one cycle in the period.'),
        responsibilities=(
            '<b>Fleet Manager</b> — runs the weekly review and produces '
            'the briefing note.<br/>'
            '<b>Operations Manager</b> — reviews the briefing and '
            'approves any operational adjustments.<br/>'
            '<b>Dispatch Supervisor</b> — implements approved '
            'adjustments in the following week\'s plan.'),
        procedure=[
            'Every Monday morning, open the <b>Truck Cycle Time</b> '
            'module.',
            'Set the date filter to cover the prior calendar week '
            '(Monday 00:00 to Sunday 23:59).',
            'Note the four KPI values: Open Cycles, Closed Last Week, '
            'Avg Cycle Time, Long Cycles.',
            'Review the Idling Rate chart. Investigate any truck with '
            'an idling percentage above thirty percent — talk to the '
            'driver, review the visit log, and identify whether the '
            'cause is operational (long customer waits) or behavioural '
            '(unnecessary engine running).',
            'Review the Cycle History table, sorted by Duration '
            'descending. For each cycle exceeding twenty-four hours, '
            'verify the multi-day journey was planned (e.g., Cebu '
            'route) and not the result of an unrecognised breakdown or '
            'detour.',
            'Compile a one-page briefing note for the Operations '
            'Manager. Include: KPI summary, top three idling '
            'offenders, top three long cycles, and recommended '
            'actions.',
            'Discuss findings at the Monday operations meeting. '
            'Document approved actions in the meeting minutes.',
            'Implement approved actions in the following week\'s '
            'planning.',
        ],
        records=(
            'TruckCycle rows in the database; SiteVisit rows linked to '
            'each cycle; weekly briefing notes (filed by the Fleet '
            'Manager); operations meeting minutes.'),
        frequency='Weekly — every Monday morning.',
        references=(
            'SOP-001 Daily Dispatch<br/>'
            'SOP-003 Breakdown Reporting'),
    )

    return out