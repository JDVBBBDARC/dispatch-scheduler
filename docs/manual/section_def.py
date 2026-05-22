"""Sections D (Quality Management), E (Technical), F (Appendices)."""
from reportlab.platypus import PageBreak
from reportlab.lib.units import cm
from helpers import (h_section, h1, h2, h3, p, pj, lead, sp, code,
                      bullet_list, numbered_list, std_table, callout,
                      screenshot_placeholder, caption, S)
from diagrams import deployment_topology_diagram


# ════════════════════════════════════════════════════════════════════════
# SECTION D — Quality Management
# ════════════════════════════════════════════════════════════════════════
def section_d():
    out = []
    out.append(PageBreak())
    out.append(h_section('Section D — Quality Management'))
    out.append(lead(
        'This section maps the operational use of the Dispatch '
        'Scheduler System to the requirements of ISO 9001:2015. It '
        'describes how the system supports quality control, change '
        'management, access control, auditability, and continual '
        'improvement.'))

    # ── D.1 Data Quality Controls ──────────────────────────────────────
    out.append(h1('D.1 Data Quality Controls'))
    out.append(pj(
        'Operational decisions are only as good as the data on which '
        'they are based. The system enforces data quality through a '
        'combination of validation, defaults, and reconciliation '
        'procedures.'))

    dq_rows = [
        ['Control', 'Mechanism', 'Owner'],
        ['Required field validation',
         'The application rejects trip rows missing Driver, Plate, '
         'Product, or Client.', 'Dispatcher'],
        ['Type-qualified driver assignment',
         'Driver dropdowns on trip rows are filtered to drivers '
         'qualified for the truck type of the Wave.', 'System'],
        ['Plate availability check',
         'Plates currently flagged as Under Repair are hidden from '
         'the Plate dropdown on new trip rows.', 'System / Fleet Manager'],
        ['Status workflow integrity',
         'Trip status cycles through Pending → Loading → In Transit → '
         'Delivered. Backward transitions require explicit dropdown '
         'selection.', 'Dispatcher'],
        ['GPS evidence for tolls',
         'Auto-fills carry their source CartrackEvent and SiteVisit '
         'IDs for traceability.', 'System'],
        ['Daily reconciliation',
         'Every Delivered trip must have either an auto-filled toll '
         'or a manually entered toll with a Notes annotation by '
         'end-of-day.', 'Dispatcher'],
        ['Weekly toll reconciliation',
         'Finance compares system toll figures against physical '
         'receipts and RFID statements every Monday.', 'Finance'],
        ['Quarterly access review',
         'Management Representative confirms each active user '
         'account is still required.', 'Management Rep.'],
    ]
    out.append(std_table(dq_rows, col_widths=[4.5 * cm, 8 * cm, 4 * cm]))

    # ── D.2 Change Management ──────────────────────────────────────────
    out.append(h1('D.2 Change Management'))
    out.append(pj(
        'Changes to the application — whether new modules, bug fixes, '
        'or master-data restructuring — follow a controlled release '
        'process to prevent operational disruption.'))

    out.append(h2('Change Categories'))
    cm_rows = [
        ['Category', 'Examples', 'Approval'],
        ['Master Data',  'Adding a new client, new truck type, new driver.',
         'Operations Manager'],
        ['Configuration','Adjusting poll cadence, drive-by threshold, '
                         'cycle hard-close window.', 'IT Administrator + Ops Manager'],
        ['Code change',  'New module, bug fix, UI enhancement.',
         'IT Administrator + Management Representative'],
        ['Schema migration', 'Adding a database column, new entity type.',
         'IT Administrator + Management Representative'],
        ['Vendor integration','New Cartrack endpoint, Google Sheets '
                              'webhook change.', 'IT Administrator + Ops Manager'],
    ]
    out.append(std_table(cm_rows, col_widths=[3.5 * cm, 7.5 * cm, 5.5 * cm]))

    out.append(h2('Release Procedure'))
    for x in numbered_list([
        'Proposed changes are documented in writing (email, ticket, '
        'or change request form).',
        'Changes are developed and tested in a separate Git branch.',
        'Approval is obtained from the appropriate role(s) per the '
        'category table above.',
        'Code is merged to the main branch and tagged with a version '
        'number.',
        'Deployment to production is performed during a maintenance '
        'window, typically 6:00 AM on a non-operational day.',
        'The Revision History on page 2 of this manual is updated, '
        'and a new version of the manual is distributed.',
        'Post-deployment, the IT Administrator monitors the system '
        'for one hour to confirm normal operation.',
    ]): out.append(x)
    out.append(callout(
        'Roll-back',
        'Every code release is preceded by a database backup '
        '(SOP-005). In the event of a critical post-release defect, '
        'the IT Administrator may roll back to the prior code version '
        'and, if necessary, restore the pre-release database backup. '
        'Roll-backs are reported to the Management Representative '
        'within twenty-four hours.',
        kind='warn'))

    # ── D.3 Access Control ────────────────────────────────────────────
    out.append(h1('D.3 Access Control'))
    out.append(pj(
        'Access to the Dispatch Scheduler is granted on the principle '
        'of least privilege. There is no anonymous access — every '
        'request to every page is authenticated against the user '
        'database.'))
    for x in bullet_list([
        'Each user has a unique username. Shared accounts are '
        'prohibited.',
        'Passwords are hashed using a one-way cryptographic function. '
        'The plaintext password is never stored.',
        'A new user\'s initial password is randomly generated and '
        'communicated out-of-band; the user must change it on first '
        'login.',
        'Passwords expire every ninety days and must be changed.',
        'Sessions expire automatically after twelve hours of '
        'inactivity.',
        'Failed login attempts are logged. Five consecutive failures '
        'against a single account trigger a fifteen-minute lockout.',
        'The IT Administrator reviews the active user list quarterly, '
        'in coordination with HR.',
    ]): out.append(x)

    # ── D.4 Audit Trail ───────────────────────────────────────────────
    out.append(h1('D.4 Audit Trail'))
    out.append(pj(
        'The system maintains an audit trail across the operational '
        'data sufficient to reconstruct what happened, when, and to '
        'which records, in support of internal and external audits.'))
    audit_rows = [
        ['Audit Element', 'Captured? (Y/N)', 'Retention'],
        ['Trip record creation timestamp', 'Y', 'Indefinite'],
        ['Trip record field changes (full history)',
         'Partial (last update timestamp)', 'Indefinite'],
        ['Trip status transitions',
         'Y (timestamped per change)', 'Indefinite'],
        ['Login successes / failures',
         'Y (via web-server logs)', '60 days'],
        ['Breakdown record creation / closure',
         'Y', 'Indefinite'],
        ['Toll auto-fill events',
         'Y (via CartrackEvent + SiteVisit)', '60 days for events, '
         'indefinite for the resulting TripRecord.toll_fee'],
        ['Cartrack polling worker runs',
         'Y (always-on task log)', '60 days'],
        ['Database backups',
         'Y (daily file snapshots)', '7 daily + weekly off-site'],
    ]
    out.append(std_table(audit_rows, col_widths=[6.5 * cm, 4.5 * cm, 5.5 * cm]))

    # ── D.5 Backup & Recovery ─────────────────────────────────────────
    out.append(h1('D.5 Backup and Recovery'))
    out.append(pj(
        'Operational continuity is protected by a layered backup '
        'strategy. See SOP-005 for the full procedure. Recovery '
        'objectives are stated below.'))
    rto_rows = [
        ['Metric', 'Target'],
        ['Recovery Time Objective (RTO)',
         '4 hours — from incident detection to operational restore.'],
        ['Recovery Point Objective (RPO)',
         '24 hours — at worst, one day of operational data is lost.'],
        ['Backup Frequency',
         'Daily (automated); Weekly (off-site copy).'],
        ['Backup Retention',
         '7 daily on-host + indefinite weekly off-site.'],
        ['Restore Testing',
         'Quarterly drill, documented in the restore-drill log.'],
    ]
    out.append(std_table(rto_rows, col_widths=[6 * cm, 10.5 * cm]))

    return out


# ════════════════════════════════════════════════════════════════════════
# SECTION E — Technical Documentation
# ════════════════════════════════════════════════════════════════════════
def section_e():
    out = []
    out.append(PageBreak())
    out.append(h_section('Section E — Technical Documentation'))
    out.append(lead(
        'This section provides technical reference material for the '
        'IT Administrator and external auditors. It complements the '
        'operational sections by documenting the system\'s internal '
        'structure: data model, API endpoints, integration points, '
        'and deployment topology.'))

    # ── E.1 System Architecture ───────────────────────────────────────
    out.append(h1('E.1 Deployment Topology'))
    out.append(pj(
        'The production deployment runs on PythonAnywhere under the '
        'paid Developer tier. The web application is served by '
        'PythonAnywhere\'s WSGI server. A separate always-on task '
        'runs the GPS polling worker. Both processes read the same '
        'environment variables and the same SQLite database file.'))
    out.append(sp(6))
    out.append(deployment_topology_diagram())
    out.append(caption('Figure E-1: Deployment topology. Both the Flask web '
                        'application and the GPS polling worker run as separate '
                        'processes on the PythonAnywhere host and share the '
                        'SQLite database. The Cartrack API and Google Sheets '
                        'webhook are external HTTPS dependencies.'))

    out.append(h2('Process List'))
    proc_rows = [
        ['Process', 'Purpose', 'Trigger'],
        ['Web application (Flask)',
         'Serves user-facing pages and JSON APIs.',
         'PythonAnywhere WSGI on inbound HTTPS request.'],
        ['Polling worker (cartrack_poll.py)',
         'Fetches GPS positions, geofence events, processes site visits, '
         'opens/closes cycles, auto-fills tolls.',
         'PythonAnywhere always-on task, restart on host reboot.'],
        ['Database (SQLite)',
         'Single-file relational store.',
         'Always available (file-backed).'],
    ]
    out.append(std_table(proc_rows, col_widths=[4.5 * cm, 7.5 * cm, 4.5 * cm]))

    # ── E.2 Database Schema ───────────────────────────────────────────
    out.append(h1('E.2 Database Schema (Key Entities)'))
    out.append(pj(
        'The database uses SQLite via SQLAlchemy ORM. The principal '
        'entities and their relationships are summarised below. Full '
        'schema definitions live in <font face="Courier">models_v2.py</font>.'))

    ent_rows = [
        ['Entity', 'Purpose', 'Key Relations'],
        ['TruckTypeDef',  'Truck type catalogue (DT, TH, MDT, …).',
                          'Has many Plates, Waves.'],
        ['Driver',        'Personnel who drives trucks.',
                          'Qualified for one or more TruckTypeDefs.'],
        ['Helper',        'Personnel who assists drivers.',
                          'Independent — assignable to any trip.'],
        ['Plate',         'Vehicle in the fleet.',
                          'Belongs to one TruckTypeDef. May map to one Cartrack vehicle.'],
        ['Client',        'Customer / consignee.',
                          'Used in trip records.'],
        ['Product',       'Material being transported.',
                          'Used in trip records.'],
        ['Wave',          'Group of trips on one date for one truck type.',
                          'Has many TripRecords.'],
        ['TripRecord',    'A single delivery / pickup assignment.',
                          'References Wave, Driver, Helper, Plate, Product, Client.'],
        ['BreakdownLog',  'Plate-out-of-service event.',
                          'References one Plate.'],
        ['CartrackTruckState','Latest GPS snapshot per plate.',
                              'One-to-one with Plate.'],
        ['CartrackGeofence','Geofence imported from Cartrack.',
                            'Categorised: home, customer, quarry, toll, …'],
        ['CartrackEvent', 'Raw GPS event (enter / exit a geofence or plaza).',
                          'References Plate, optionally CartrackGeofence.'],
        ['SiteVisit',     'Aggregated visit to a geofence (enter + exit pair).',
                          'References Plate, CartrackGeofence, optionally TripRecord and TruckCycle.'],
        ['TruckCycle',    'One round trip from home base and back.',
                          'References Plate. Has many SiteVisits.'],
    ]
    out.append(std_table(ent_rows, col_widths=[3.5 * cm, 6 * cm, 7 * cm]))

    # ── E.3 API Endpoints ─────────────────────────────────────────────
    out.append(h1('E.3 Selected API Endpoints'))
    out.append(pj(
        'The application exposes a number of JSON endpoints used '
        'internally by the front-end. They are documented here as '
        'reference for the IT Administrator. All endpoints require '
        'an authenticated session.'))
    api_rows = [
        ['Endpoint', 'Method', 'Purpose'],
        ['/api/dashboard/kpis',                'GET',  'Headline KPI figures (now includes GPS Toll aggregate).'],
        ['/api/dashboard/fleet-utilization',   'GET',  'Per-truck-type utilisation.'],
        ['/api/dashboard/driver-truck-ratio',  'GET',  'Driver vs assigned plate ratio.'],
        ['/api/dashboard/breakdown-hours',     'GET',  'Per-plate downtime histogram.'],
        ['/api/cycle-time/summary',            'GET',  'Cycle KPIs + open-cycle list.'],
        ['/api/cycle-time/cycles',             'GET',  'Filtered cycle history (legacy, used by Excel export).'],
        ['/api/cycle-time/plates',             'GET',  'Plate-centric live view used by the redesigned Plate Status table.'],
        ['/api/cycle-time/plate/&lt;id&gt;/cycles', 'GET', 'List of cycles for one plate — feeds the cycle-picker chips when a row is expanded.'],
        ['/api/cycle-time/cycle/&lt;id&gt;/timeline', 'GET', 'Full chronological audit trail of one cycle (visits + plaza events + in-progress stops).'],
        ['/api/cycle-time/idling',             'GET',  'Per-plate idling statistics.'],
        ['/api/cycle-time/filters',            'GET',  'Dropdown options for the page.'],
        ['/api/cycle-time/export',             'GET',  'Excel export of cycles.'],
        ['/api/cycle-time/sync-geofences',     'POST', 'Admin trigger to pull geofences from Cartrack (uses limit=1000).'],
        ['/api/cycle-time/settings',           'GET',  'Read the current min-visit and stop-detection thresholds.'],
        ['/api/cycle-time/settings',           'POST', 'Admin-only: update the thresholds (persists to AppSetting; polling worker picks up on next poll).'],
        ['/api/cycle-time/clear-logs',         'POST', 'Admin-only: purge tracking rows (SiteVisit, TruckCycle, CartrackEvent) older than a required cutoff date. Requires confirm="CLEAR".'],
        ['/api/toll-log/summary',              'GET',  'Toll Log KPI figures.'],
        ['/api/toll-log/events',               'GET',  'Filtered list of plaza events.'],
        ['/api/toll-log/export',               'GET',  'Excel export of events.'],
        ['/api/cartrack/status',               'GET',  'Diagnostic status of the GPS integration.'],
        ['/api/cartrack/poll-now',             'POST', 'Manually trigger a polling cycle.'],
        ['/api/cartrack/auto-map',             'POST', 'Auto-link plates to Cartrack vehicles.'],
        ['/api/trip/save',                     'POST', 'Create / duplicate a trip. The Schedule cross-wave copy dropdown uses this with a target wave_id.'],
        ['/api/sync-to-sheets',                'POST', 'Push operational data to Google Sheets.'],
    ]
    out.append(std_table(api_rows, col_widths=[6.5 * cm, 1.6 * cm, 8.4 * cm]))

    # ── E.4 Integration Points ────────────────────────────────────────
    out.append(h1('E.4 External Integrations'))
    out.append(h2('Cartrack Fleet REST API'))
    out.append(pj(
        'Endpoint host: <font face="Courier">fleetapi-ph.cartrack.com</font>. '
        'Authentication uses HTTP Basic with credentials stored in '
        'environment variables (CARTRACK_USERNAME, CARTRACK_PASSWORD). '
        'The polling worker fetches per-vehicle status approximately '
        'once per minute and processes the geofence-id list and '
        'idling / ignition flags to update local state.'))
    out.append(h2('Google Sheets Webhook'))
    out.append(pj(
        'When configured, the application can push trip and breakdown '
        'data to a Google Sheet via a Google Apps Script webhook. The '
        'URL is stored in the AppSetting table and is invoked from the '
        '/api/sync-to-sheets endpoint. Push is one-way (no read-back).'))

    return out


# ════════════════════════════════════════════════════════════════════════
# SECTION F — Appendices
# ════════════════════════════════════════════════════════════════════════
def section_f():
    out = []
    out.append(PageBreak())
    out.append(h_section('Section F — Appendices'))
    out.append(lead(
        'Reference material that supports the operational and quality '
        'sections of this manual: troubleshooting, forms, contact '
        'information, and a quick-reference cheat sheet.'))

    # ── F.1 Troubleshooting Guide ─────────────────────────────────────
    out.append(h1('F.1 Troubleshooting Guide'))
    out.append(p('Common operational issues and their resolutions.'))

    ts_rows = [
        ['Symptom', 'Probable Cause', 'Resolution'],
        ['Cannot log in — "invalid credentials"',
         'Password expired, mistyped, or account deactivated.',
         'Try again carefully. If still failing, contact the IT '
         'Administrator for a password reset.'],
        ['Trip toll_fee shows 0 after delivery',
         'GPS evidence not captured — plate not mapped to Cartrack, '
         'plaza missed by the polling worker, or trip outside the '
         'date-match window.',
         'Enter the toll manually from the physical receipt. Add a '
         'Notes annotation. Investigate per SOP-004.'],
        ['Truck shows live status "NO DATA"',
         'Plate not mapped to Cartrack, or the Cartrack device is '
         'offline.',
         'Confirm Cartrack mapping in Master Data. Check the device '
         'in the Cartrack Fleet Web map.'],
        ['Cycle stays "ongoing" after truck returns',
         'Polling worker missed the home-geofence re-entry; or the '
         'cycle is genuinely multi-day.',
         'Wait for the next polling cycle (one minute). If still '
         'unresolved after one hour, alert the IT Administrator.'],
        ['Dashboard KPIs differ from expected totals',
         'Trips left in Pending / Loading / In Transit are excluded '
         'from Delivered counts.',
         'Close out remaining trip statuses per SOP-002.'],
        ['Cartrack diagnostic shows "not configured"',
         'Environment variables not set on the always-on task.',
         'IT Administrator: confirm CARTRACK_USERNAME and '
         'CARTRACK_PASSWORD are set in both the Web tab and the '
         'always-on task environment.'],
        ['Google Sheets sync returns an error',
         'Webhook URL mis-configured or expired Apps Script trigger.',
         'Verify the webhook URL in Admin / Settings. Re-publish the '
         'Google Apps Script if needed.'],
    ]
    out.append(std_table(ts_rows, col_widths=[5 * cm, 5.5 * cm, 6 * cm]))

    # ── F.2 Forms & Records ──────────────────────────────────────────
    out.append(h1('F.2 Forms and Records'))
    out.append(p('The following forms support the SOPs. Each form is '
                  'identified by a unique code (FM-XXX) and maintained '
                  'by the Management Representative.'))
    fm_rows = [
        ['Code', 'Title', 'Used in SOP', 'Custodian'],
        ['FM-001', 'Training Acknowledgement Record',     'All SOPs',     'Mgmt. Rep.'],
        ['FM-002', 'Daily Dispatch Plan (printed copy)',  'SOP-001',      'Dispatch Supervisor'],
        ['FM-003', 'End-of-Day Reconciliation Checklist', 'SOP-002',      'Dispatcher'],
        ['FM-004', 'Breakdown Notification Slip',         'SOP-003',      'Fleet Manager'],
        ['FM-005', 'Weekly Toll Reconciliation Worksheet','SOP-004',      'Finance Officer'],
        ['FM-006', 'Backup / Restore Drill Log',          'SOP-005',      'IT Administrator'],
        ['FM-007', 'User Access Request / Revocation',    'SOP-005',      'IT Administrator'],
        ['FM-008', 'Weekly Cycle Time Briefing',          'SOP-006',      'Fleet Manager'],
    ]
    out.append(std_table(fm_rows,
                          col_widths=[2 * cm, 7 * cm, 3 * cm, 4.5 * cm]))

    # ── F.3 Quick Reference ──────────────────────────────────────────
    out.append(h1('F.3 Quick Reference — Common Tasks'))

    qr_rows = [
        ['Task', 'Module', 'Steps'],
        ['Add a new trip',
         'Schedule',
         '+ Add Row → fill fields → blur to save.'],
        ['Duplicate a trip (same wave)',
         'Schedule',
         'Click the copy icon (📋) on the row.'],
        ['Duplicate a trip to another wave',
         'Schedule',
         'Click the caret (▼) next to the copy icon → pick target wave.'],
        ['Cancel a trip',
         'Schedule',
         'Click Status badge dropdown → Cancelled.'],
        ['Log a breakdown',
         'Breakdown',
         '+ Log Breakdown → fill form → Save.'],
        ['Compute a toll',
         'Toll Calculator',
         'Pick expressway → class → entry → exit.'],
        ['Enter trip toll fee (manual)',
         'Schedule',
         'Type the toll from the physical receipt into the trip\'s Toll Fee column.'],
        ['Check today\'s GPS-detected toll total',
         'Dashboard',
         'Look at the "GPS Toll" KPI card (purple, broadcast icon).'],
        ['Drill into GPS-detected toll events',
         'Toll Log',
         'Open /toll-log (or click the GPS Toll card on Dashboard).'],
        ['Export the toll log',
         'Toll Log',
         'Set filters → Export to Excel.'],
        ['Map a plate to GPS',
         'Master Data',
         'Plates card → broadcast icon → pick vehicle.'],
        ['Run a poll on demand',
         'Master Data',
         'Plates card toolbar → Poll Now.'],
        ['Push to Google Sheets',
         'Reports',
         'Set date range → Sync to Sheets.'],
        ['Pull latest geofences',
         'Truck Cycle Time',
         'Toolbar → Sync Geofences.'],
        ['See where a truck is right now',
         'Truck Cycle Time',
         'Look at the Plate Status table — open cycles at top.'],
        ['View a truck\'s full journey log',
         'Truck Cycle Time',
         'Click the truck\'s row → pick a cycle chip → audit trail timeline appears below.'],
        ['Investigate a long cycle',
         'Truck Cycle Time',
         'Filter Cycle Length = Long, then expand the plate row to view the timeline.'],
        ['Adjust dwell or stop thresholds',
         'Truck Cycle Time',
         'Settings button → modify values → Save (admin only).'],
        ['Clear trial-period tracking data',
         'Truck Cycle Time',
         'Settings → Danger Zone → pick cutoff date → type CLEAR → confirm (admin only).'],
        ['Add a manual geofence (workaround)',
         'IT Admin only',
         'Edit manual_geofences.json at project root; polling worker re-reads on next poll.'],
    ]
    out.append(std_table(qr_rows, col_widths=[5.5 * cm, 3.5 * cm, 7.5 * cm]))

    # ── F.4 Contact Information ──────────────────────────────────────
    out.append(h1('F.4 Contact Information'))
    out.append(p('Key contacts for system support. Update this table '
                  'before printing.'))
    contact_rows = [
        ['Role', 'Name', 'Contact'],
        ['Operations Manager',          '[ TO BE FILLED ]', '[ TO BE FILLED ]'],
        ['Dispatch Supervisor',         '[ TO BE FILLED ]', '[ TO BE FILLED ]'],
        ['Fleet Manager',               '[ TO BE FILLED ]', '[ TO BE FILLED ]'],
        ['Finance Officer',             '[ TO BE FILLED ]', '[ TO BE FILLED ]'],
        ['IT Administrator',            '[ TO BE FILLED ]', '[ TO BE FILLED ]'],
        ['Management Representative',   '[ TO BE FILLED ]', '[ TO BE FILLED ]'],
        ['Cartrack PH Support',         'Cartrack Customer Care',
                                         '+63 2 8 555 3000 / support@cartrack.ph'],
    ]
    out.append(std_table(contact_rows,
                          col_widths=[5.5 * cm, 5.5 * cm, 5.5 * cm]))

    # ── F.5 Document History / End ──────────────────────────────────
    out.append(h1('F.5 End of Document'))
    out.append(pj(
        'This concludes the Dispatch Scheduler System Manual, version '
        f'{__import__("styles").DOC_VERSION}. The document is '
        'controlled by the Management Representative; revisions are '
        'logged in the Document Control page (Section A front matter).'))
    out.append(sp(20))
    out.append(callout(
        'Feedback Welcome',
        'Errors, omissions, and suggestions for improvement are '
        'welcomed. Submit feedback in writing to the Management '
        'Representative for inclusion in the next scheduled revision.',
        kind='ok'))

    return out
