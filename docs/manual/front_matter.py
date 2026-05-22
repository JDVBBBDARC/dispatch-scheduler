"""Cover page, document control, table of contents, glossary."""
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import (Paragraph, Spacer, PageBreak, Table,
                                 TableStyle, KeepTogether)
from reportlab.lib.styles import ParagraphStyle

from styles import (build_styles, MAROON, MAROON_LIGHT, GREY_DARK, GREY_MID,
                     GREY_BORDER, GREY_LIGHT, COMPANY_NAME, DOC_TITLE,
                     DOC_ID, DOC_VERSION, DOC_DATE, PAGE_SIZE,
                     MARGIN_LEFT, MARGIN_RIGHT)
from helpers import (h_section, h1, h2, h3, p, pj, lead, sp, code,
                      bullet_list, numbered_list, std_table, callout, S)


def cover_page():
    """Cover page — no header/footer (handled by NumberedCanvas)."""
    out = []
    out.append(sp(120))
    # Brand bar
    bar = Table([['']], colWidths=[16 * cm], rowHeights=[0.18 * cm])
    bar.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), MAROON)]))
    out.append(bar)
    out.append(sp(40))
    out.append(Paragraph(COMPANY_NAME, S['CoverSub']))
    out.append(sp(40))
    out.append(Paragraph(DOC_TITLE, S['CoverTitle']))
    out.append(sp(8))
    out.append(Paragraph('ISO 9001:2015 Quality Management System',
                          S['CoverSub']))
    out.append(sp(60))
    # Doc meta block
    meta_rows = [
        ['Document ID',  DOC_ID],
        ['Version',      DOC_VERSION],
        ['Issue Date',   DOC_DATE],
        ['Classification','Controlled Document — Internal Use'],
        ['Status',       'Approved for Use'],
    ]
    meta_rows = [[Paragraph(f'<b>{k}</b>', S['CoverMeta']),
                  Paragraph(v,             S['CoverMeta'])]
                 for k, v in meta_rows]
    meta_tbl = Table(meta_rows, colWidths=[5 * cm, 8 * cm], hAlign='CENTER')
    meta_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
    ]))
    out.append(meta_tbl)
    out.append(sp(80))
    out.append(Paragraph(
        '<i>This document is the property of Big Ben Logistics and is '
        'intended for internal use only. Reproduction or distribution '
        'outside the organisation requires written approval from the '
        'Management Representative.</i>', S['CoverMeta']))
    out.append(PageBreak())
    return out


def document_control_page():
    out = []
    out.append(h_section('Document Control'))
    out.append(pj(
        'This page records the revision history of, and the formal '
        'approvals required for, the Dispatch Scheduler System Manual. '
        'It satisfies the requirements of ISO 9001:2015 Clause 7.5.3 '
        '(Control of documented information).'))
    out.append(sp(10))

    out.append(h2('Revision History'))
    rows = [['Rev.', 'Date', 'Section(s)', 'Description of Change', 'Author']]
    rows.append(['1.0', 'May 2026', 'All', 'Initial release.', 'IT / Operations'])
    rows.append(['1.1', DOC_DATE, 'B.1, B.2, B.7, C-004, E.3, F.3',
                  'Truck Cycle Time redesigned to plate-centric view '
                  '(Plate Status + cycle picker + audit trail timeline). '
                  'Toll auto-fill decoupled from Schedule — manual entry '
                  'remains the source of truth for billing; GPS-detected '
                  'tolls surface as a separate Dashboard KPI and on the '
                  'Toll Log page. New Schedule cross-wave copy dropdown. '
                  'New Settings modal on TCT for configurable dwell + '
                  'stop-detection thresholds. New admin-only Clear Logs '
                  'with type-CLEAR confirmation. New manual geofences '
                  'workaround for any future API visibility issues. '
                  'Ad-hoc stop detection (≥ N min outside any geofence). '
                  'Timezone serialisation unified to PHT-aware ISO.',
                  'IT / Operations'])
    rows.append(['', '', '', '', ''])
    out.append(std_table(rows,
                          col_widths=[1.4 * cm, 2.6 * cm, 3 * cm, 6.5 * cm, 3 * cm]))
    out.append(sp(14))

    out.append(h2('Approval'))
    out.append(p(
        'By signing below, the listed officers confirm that this manual '
        'accurately describes the current operational use of the '
        'Dispatch Scheduler System and authorise its release as a '
        'controlled document.'))
    out.append(sp(8))
    # Signature table (blank rows for ISO auditor)
    sig_rows = [
        ['Role', 'Name', 'Signature', 'Date'],
        ['Prepared by',     '[ TO BE FILLED ]', '', ''],
        ['Reviewed by',     '[ TO BE FILLED ]', '', ''],
        ['Approved by',     '[ TO BE FILLED ]', '', ''],
        ['Mgmt. Rep. (ISO)','[ TO BE FILLED ]', '', ''],
    ]
    sig_tbl = std_table(sig_rows,
                         col_widths=[3.8 * cm, 4.5 * cm, 4.5 * cm, 3.5 * cm])
    # Force taller signature rows
    sig_tbl.setStyle(TableStyle([
        ('TOPPADDING',    (0, 1), (-1, -1), 16),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 16),
    ]))
    out.append(sig_tbl)
    out.append(sp(14))

    out.append(h2('Distribution List'))
    out.append(p(
        'This manual is distributed to the following roles. Each holder '
        'is responsible for maintaining the integrity of their copy and '
        'destroying obsolete versions when superseded.'))
    out.append(sp(4))
    dist_rows = [['Copy No.', 'Holder Role', 'Department', 'Format']]
    dist_rows += [
        ['Master', 'Management Representative', 'Quality Assurance', 'Digital (PDF) + Print'],
        ['01',     'Operations Manager',        'Operations',        'Digital (PDF)'],
        ['02',     'Dispatch Supervisor',       'Operations',        'Digital (PDF) + Print'],
        ['03',     'Fleet Manager',             'Fleet',             'Digital (PDF)'],
        ['04',     'IT Administrator',          'IT / Systems',      'Digital (PDF)'],
        ['05',     'HR / Training',             'Human Resources',   'Digital (PDF)'],
    ]
    out.append(std_table(dist_rows,
                          col_widths=[2 * cm, 5 * cm, 4.5 * cm, 5 * cm]))
    out.append(PageBreak())
    return out


def toc_page(toc_flowable):
    out = []
    out.append(h_section('Table of Contents'))
    out.append(p('Section page numbers are generated automatically from '
                  'the document structure.'))
    out.append(sp(8))
    out.append(toc_flowable)
    out.append(PageBreak())
    return out


def glossary_page():
    out = []
    out.append(h_section('Glossary & Acronyms'))
    out.append(p('The following terms are used throughout this manual.'))
    out.append(sp(6))
    rows = [['Term / Acronym', 'Definition']]
    glossary = [
        ('API',       'Application Programming Interface — the protocol used by external systems (Cartrack, Google Sheets) to exchange data with the Dispatch Scheduler.'),
        ('Auto-fill', 'The automatic populating of a TripRecord field (such as toll fee) from GPS telemetry, without manual data entry.'),
        ('BIG BEN SCM', 'Big Ben Supply Chain Management — the home base geofence. Cycles open when a truck leaves this geofence and close when it returns.'),
        ('Breakdown', 'A recorded incident in which a vehicle becomes unavailable due to mechanical, electrical, or accident-related causes.'),
        ('Cartrack',  'The fleet GPS tracking provider integrated with this system. Provides real-time vehicle positions, geofence events, and trip data.'),
        ('Cycle',     'One complete round trip: a truck exits the home geofence, performs deliveries or pickups, and returns to the home geofence.'),
        ('Dispatcher','The operations staff member responsible for assigning trips to drivers and tracking their status.'),
        ('Drive-by',  'A geofence visit shorter than the minimum dwell time (default 5 minutes) — treated as a transient touch, not a delivery stop.'),
        ('Geofence',  'A virtual boundary drawn around a real-world location (customer site, quarry, toll plaza, fuel station) used to detect vehicle entry and exit.'),
        ('Idling',    'A state in which the engine is running but the vehicle is stationary, as reported by the Cartrack telemetry.'),
        ('ISO 9001',  'International standard for Quality Management Systems (current revision: ISO 9001:2015).'),
        ('KPI',       'Key Performance Indicator. Examples in this system: trips per day, fleet utilisation, average cycle time, total toll spend.'),
        ('Master Data','The reference data shared across the application: drivers, helpers, plates, products, clients, dispatchers, truck types.'),
        ('Plate',     'A vehicle in the fleet, identified by its registration (plate number) and an internal body number (e.g., DT15, TH08).'),
        ('Plaza',     'A toll collection point on a Philippine expressway. The system maintains a matrix of inter-plaza toll fees for auto-calculation.'),
        ('PHT',       'Philippine Time (UTC+8) — the time zone used for all business dates and schedules.'),
        ('SOP',       'Standard Operating Procedure — a documented sequence of steps for executing a recurring task.'),
        ('TripRecord','The database record representing one delivery or pickup assigned to a driver, helper, and plate within a Wave.'),
        ('Truck Type','A classification of vehicles by capacity and use (e.g., DT — Dump Truck, TH — Trailer Hauler, MDT — Mini Dump Truck).'),
        ('UTC',       'Coordinated Universal Time. The server runs in UTC; all displayed times are converted to PHT.'),
        ('Wave',      'A scheduled batch of trips for a given date and truck type. A day can have multiple waves (e.g., morning and afternoon).'),
        ('WSGI',      'Web Server Gateway Interface — the Python web-app deployment standard used on PythonAnywhere.'),
    ]
    for term, defn in glossary:
        rows.append([Paragraph(f'<b>{term}</b>',
                                ParagraphStyle('G', fontName='Helvetica-Bold',
                                               fontSize=9, textColor=GREY_DARK)),
                     Paragraph(defn, S['Body'])])
    out.append(std_table(rows, col_widths=[3.6 * cm, 12.9 * cm]))
    out.append(PageBreak())
    return out
