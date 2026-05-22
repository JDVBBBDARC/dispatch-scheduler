"""Section A — System Overview & Architecture."""
from reportlab.platypus import PageBreak, KeepTogether
from reportlab.lib.units import cm
from helpers import (h_section, h1, h2, h3, p, pj, lead, sp, code,
                      bullet_list, numbered_list, std_table, callout,
                      screenshot_placeholder, caption, S)
from diagrams import architecture_diagram


def section_a():
    out = []
    out.append(h_section('Section A — System Overview'))
    out.append(lead(
        'This section introduces the Dispatch Scheduler System: its purpose, '
        'business context, architecture, modules, and the user roles that '
        'interact with it. It provides the foundation for the detailed '
        'user procedures and Standard Operating Procedures that follow in '
        'subsequent sections.'))

    # ── A.1 Purpose & Scope ─────────────────────────────────────────────
    out.append(h1('A.1 Purpose and Scope'))
    out.append(pj(
        'The Dispatch Scheduler is the central operating system for '
        'managing day-to-day fleet operations at Big Ben Logistics. It '
        'replaces the previous combination of paper-based dispatch sheets, '
        'Excel logs, and ad-hoc messaging applications with a single '
        'integrated platform accessible from any web browser.'))
    out.append(pj(
        'The system covers the full operational cycle of a delivery or '
        'pickup: from the moment a trip is scheduled, through the '
        'assignment of driver, helper, and plate, the live tracking of '
        'the truck via GPS, the recording of toll fees and breakdowns, '
        'and finally the closing of the trip with all supporting '
        'documentation.'))
    out.append(callout(
        'Scope of this Manual',
        'This manual describes the operational use of the Dispatch '
        'Scheduler Application as deployed on the Big Ben Logistics '
        'PythonAnywhere environment. It covers all modules visible to '
        'authenticated users. Source-code development, infrastructure '
        'administration, and external vendor (Cartrack, Google Sheets) '
        'configuration are outside its scope.',
        kind='iso'))

    # ── A.2 Business Context ───────────────────────────────────────────
    out.append(h1('A.2 Business Context'))
    out.append(pj(
        'Big Ben Logistics operates a mixed fleet of approximately fifty '
        'trucks across multiple categories — Dump Trucks (DT), Trailer '
        'Haulers (TH), Mini Dump Trucks (MDT), Self-Loading Trucks, and '
        'utility vehicles such as L300 vans. The fleet services '
        'construction projects, quarry-to-batching-plant routes, and '
        'general logistics across Luzon.'))
    out.append(pj(
        'A typical operating day begins before sunrise, with multiple '
        'trips per truck and frequent expressway transits. The system is '
        'designed to handle the operational complexity that arises from '
        'this scale: dozens of concurrent trips, multi-day journeys, '
        'shared drivers across truck types, breakdown rotations, and the '
        'corresponding toll-fee, fuel, and driver-incentive calculations.'))
    out.append(h2('Key Operational Inputs'))
    for x in bullet_list([
        'Trip plans confirmed the previous evening or early morning.',
        'Driver and helper attendance, recorded daily.',
        'Plate availability — accounting for breakdowns and maintenance.',
        'Customer purchase orders, delivery receipts, and reference numbers.',
        'Toll-plaza coordinates and inter-plaza fee matrices.',
        'Real-time GPS telemetry from Cartrack (vehicle position, speed, '
        'geofence events).',
    ]): out.append(x)
    out.append(h2('Key Operational Outputs'))
    for x in bullet_list([
        'A full audit trail of every assigned, completed, or cancelled trip.',
        'Daily, weekly, and monthly key-performance indicators (KPIs).',
        'Auto-filled toll fees per trip, where GPS evidence is available.',
        'Cycle-time analytics — how long each truck spends per round trip.',
        'Idling-rate analytics at customer and quarry geofences.',
        'Exportable reports in Excel and Google Sheets formats for '
        'finance, payroll, and management review.',
    ]): out.append(x)

    # ── A.3 System Architecture ────────────────────────────────────────
    out.append(h1('A.3 System Architecture'))
    out.append(pj(
        'The Dispatch Scheduler follows a three-tier web-application '
        'architecture. The presentation tier renders to any modern '
        'browser. The application tier runs a Flask Python application '
        'hosted on PythonAnywhere. The data tier is a SQLite database '
        'that persists all operational records. Real-time GPS data is '
        'consumed from Cartrack via a REST API and stored in the same '
        'database for unified reporting.'))
    out.append(sp(6))
    out.append(architecture_diagram())
    out.append(caption('Figure A-1: High-level system architecture. '
                        'Browser sessions reach the Flask web app over HTTPS; '
                        'a parallel always-on polling worker ingests GPS data '
                        'from the Cartrack API. Both processes share the same '
                        'SQLite database.'))

    out.append(h2('Major Components'))
    arch_rows = [
        ['Component', 'Technology', 'Function'],
        ['Web UI',             'HTML5, Bootstrap 5, vanilla JS, Chart.js',
         'Browser-rendered pages for dispatch staff, supervisors, and management.'],
        ['Application',        'Python 3, Flask, Flask-Login, SQLAlchemy',
         'Routes requests, validates input, applies business rules, returns JSON or HTML.'],
        ['Database',           'SQLite 3',
         'Stores trips, waves, master data, breakdowns, GPS state, geofences, cycles.'],
        ['GPS provider',       'Cartrack Fleet REST API',
         'Vehicle positions, geofence events, ignition / idling status, trip history.'],
        ['Sheets sync',        'Google Apps Script webhook',
         'Outbound push of structured data to a shared Google Sheet for finance.'],
        ['Polling worker',     'Standalone Python script (cartrack_poll.py)',
         'Runs continuously on a PythonAnywhere always-on task to ingest GPS data.'],
        ['Authentication',     'Username + password, hashed (Flask-Login session)',
         'Restricts every page to authenticated users.'],
    ]
    out.append(std_table(arch_rows,
                          col_widths=[3.6 * cm, 4.8 * cm, 8.1 * cm]))

    out.append(h2('Hosting & Availability'))
    out.append(pj(
        'The production environment is hosted on PythonAnywhere under a '
        'paid Developer tier. The application is reachable at a https '
        'URL and is restricted to authenticated Big Ben Logistics users. '
        'The polling worker runs as an always-on task on the same host, '
        'so GPS data continues to flow even when no operator is logged '
        'into the web interface. Daily CPU budget is approximately five '
        'thousand seconds, which comfortably accommodates a sixty-second '
        'polling cadence across the full fleet.'))

    # ── A.4 Modules Overview ──────────────────────────────────────────
    out.append(h1('A.4 Modules Overview'))
    out.append(p('The application is organised into nine functional '
                  'modules, each accessible from the left-hand sidebar.'))

    mod_rows = [
        ['#', 'Module', 'Primary Users', 'Purpose'],
        ['1', 'Dashboard',         'All',
         'Snapshot of today\'s operations — trip counts, fleet utilisation, '
         'cycle time, breakdowns, KPIs.'],
        ['2', 'Schedule',          'Dispatchers, Supervisors',
         'Create and edit the daily trip plan, assign personnel and plates, '
         'update trip status.'],
        ['3', 'Master Data',       'Operations Manager, IT',
         'Manage drivers, helpers, plates, products, clients, dispatchers, '
         'truck types, and GPS mappings.'],
        ['4', 'Breakdown',         'Fleet Manager, Mechanics',
         'Record incidents that take a plate out of service; track repair '
         'status and downtime.'],
        ['5', 'Toll Calculator',   'Dispatchers',
         'Compute the expected toll fee between any two plazas on any '
         'expressway, with multi-route support.'],
        ['6', 'Toll Log',          'Dispatchers, Finance',
         'View every GPS-detected plaza event in chronological order; '
         'export to Excel.'],
        ['7', 'Truck Cycle Time',  'Fleet Manager, Management',
         'Live plate status, per-truck audit trail (visits, plaza events, '
         'in-progress stops), idling-rate ranking, multi-day cycle '
         'tracking. Configurable thresholds and admin Clear Logs.'],
        ['8', 'Reports',           'Management, Finance',
         'Aggregated KPIs and trend charts across configurable date ranges.'],
        ['9', 'Admin / Settings',  'IT, Management Representative',
         'User account management, password resets, environment configuration.'],
    ]
    out.append(std_table(mod_rows,
                          col_widths=[0.8 * cm, 3.3 * cm, 4.2 * cm, 8.2 * cm]))

    # ── A.5 User Roles ────────────────────────────────────────────────
    out.append(h1('A.5 User Roles and Responsibilities'))
    out.append(pj(
        'The system uses session-based authentication. There are no '
        'in-application permission tiers at the time of writing — every '
        'authenticated user has access to every module. Access control '
        'is therefore exercised through account provisioning: only the '
        'roles listed below are granted accounts, and each user is '
        'expected to operate within the responsibilities described.'))
    role_rows = [
        ['Role', 'Modules Used (Primary)', 'Key Responsibilities'],
        ['Dispatcher',
         'Schedule, Toll Calculator, Toll Log',
         'Build the daily plan, assign trips, update statuses, verify auto-filled tolls.'],
        ['Dispatch Supervisor',
         'Schedule, Dashboard, Reports',
         'Approve the plan, monitor execution, intervene on exceptions, sign off on daily totals.'],
        ['Fleet Manager',
         'Breakdown, Truck Cycle Time, Master Data',
         'Maintain plate availability, investigate long cycle times, manage maintenance schedules.'],
        ['Operations Manager',
         'All',
         'Cross-functional oversight; final accountability for operational metrics.'],
        ['Finance Officer',
         'Toll Log, Reports',
         'Reconcile auto-filled tolls against receipts; produce monthly cost reports.'],
        ['IT Administrator',
         'Admin / Settings, Master Data',
         'Provision and de-provision user accounts; manage environment variables and integrations.'],
        ['Management Representative (ISO)',
         'All',
         'Custodian of this manual; conducts periodic reviews and authorises revisions.'],
    ]
    out.append(std_table(role_rows,
                          col_widths=[3.5 * cm, 4.2 * cm, 8.8 * cm]))
    out.append(callout(
        'Account Provisioning',
        'New user accounts are created exclusively by the IT Administrator '
        'on written request from the Operations Manager. Accounts of '
        'staff leaving the organisation are deactivated within one '
        'business day of separation. See SOP-005 (Data Backup and User '
        'Access Management).',
        kind='iso'))

    # ── A.6 Operating Environment ──────────────────────────────────────
    out.append(h1('A.6 Operating Environment'))
    out.append(h2('Client-Side Requirements'))
    for x in bullet_list([
        'Any modern web browser released within the last three years — '
        'Google Chrome, Microsoft Edge, Mozilla Firefox, or Safari.',
        'A stable internet connection. Mobile data is sufficient for '
        'occasional checks but a wired or Wi-Fi connection is '
        'recommended for dispatch workstations.',
        'A screen resolution of at least 1280 by 720 pixels. The '
        'interface adapts to smaller devices but is optimised for a '
        'full-size workstation monitor.',
    ]): out.append(x)

    out.append(h2('Time Zone Convention'))
    out.append(pj(
        'All business dates and schedules use Philippine Time (UTC+8). '
        'The application server runs in UTC internally and converts to '
        'PHT at display time. Operators are not expected to perform '
        'time-zone arithmetic.'))

    out.append(h2('Network Dependencies'))
    out.append(pj(
        'The application requires outbound HTTPS access to the Cartrack '
        'Fleet API endpoint and, when configured, to the Google Apps '
        'Script webhook. Both endpoints must be reachable from the '
        'PythonAnywhere host. The IT Administrator maintains the '
        'allow-list of permitted external services.'))

    return out
