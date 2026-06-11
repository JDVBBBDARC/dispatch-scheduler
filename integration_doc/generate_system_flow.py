"""Generate ERP Repair Request Integration — System Flow PDF.

One-shot script. Output: ERP_INTEGRATION_SYSTEM_FLOW.pdf at project root.

This is a deliverable for the IT team — a structured document describing
how the Dispatch Scheduler app will consume the ERP Repair Request API.
Intended to be attached to a Messenger/email message to the IT contact
so they can review the integration approach before issuing a service
account / refresh token.
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, PageBreak,
                                 Table, TableStyle, KeepTogether)
from reportlab.pdfgen.canvas import Canvas
from datetime import date
import os

# ── Palette ─────────────────────────────────────────────────────────
MAROON       = colors.HexColor('#8B1A2B')
MAROON_LIGHT = colors.HexColor('#F5E6E8')
GREY_DARK    = colors.HexColor('#2C3E50')
GREY_MID     = colors.HexColor('#7F8C8D')
GREY_LIGHT   = colors.HexColor('#ECEFF1')
GREY_BORDER  = colors.HexColor('#D5DBDB')
BLUE_INFO    = colors.HexColor('#2980B9')
BLUE_LIGHT   = colors.HexColor('#EBF5FB')
ORANGE_WARN  = colors.HexColor('#D35400')
ORANGE_LIGHT = colors.HexColor('#FDF2E9')
GREEN_OK     = colors.HexColor('#27AE60')
GREEN_LIGHT  = colors.HexColor('#E8F8F0')


def build_styles():
    base = getSampleStyleSheet()
    S = {}
    S['Body'] = ParagraphStyle('Body', parent=base['BodyText'],
        fontName='Helvetica', fontSize=10, leading=14,
        textColor=GREY_DARK, spaceAfter=6)
    S['BodyJ'] = ParagraphStyle('BodyJ', parent=S['Body'], alignment=4)
    S['Lead'] = ParagraphStyle('Lead', parent=S['Body'], fontSize=11,
        leading=16, spaceAfter=10)
    S['Title'] = ParagraphStyle('Title', parent=base['Title'],
        fontName='Helvetica-Bold', fontSize=24, leading=30,
        textColor=MAROON, alignment=1, spaceAfter=12)
    S['Subtitle'] = ParagraphStyle('Subtitle', parent=base['Normal'],
        fontName='Helvetica', fontSize=14, leading=18,
        textColor=GREY_DARK, alignment=1, spaceAfter=24)
    S['H1'] = ParagraphStyle('H1', parent=base['Heading1'],
        fontName='Helvetica-Bold', fontSize=16, leading=20,
        textColor=MAROON, spaceBefore=18, spaceAfter=10, keepWithNext=1)
    S['H2'] = ParagraphStyle('H2', parent=base['Heading2'],
        fontName='Helvetica-Bold', fontSize=12, leading=16,
        textColor=GREY_DARK, spaceBefore=10, spaceAfter=4, keepWithNext=1)
    S['Code'] = ParagraphStyle('Code', parent=S['Body'],
        fontName='Courier', fontSize=8.5, leading=11, leftIndent=8,
        backColor=GREY_LIGHT, borderPadding=6, borderColor=GREY_BORDER,
        borderWidth=0.5, spaceAfter=10)
    S['Caption'] = ParagraphStyle('Caption', parent=S['Body'],
        fontSize=9, leading=12, textColor=GREY_MID,
        alignment=1, spaceBefore=2, spaceAfter=12)
    return S


S = build_styles()


def std_table(rows, col_widths, header=True):
    """Build a styled table. Cell strings are auto-wrapped in Paragraph
    objects so long content flows onto multiple lines within the column
    width instead of overflowing the page edge."""
    cell_style = ParagraphStyle('Cell',
        fontName='Helvetica', fontSize=9, leading=12, textColor=GREY_DARK)
    header_style = ParagraphStyle('CellH',
        fontName='Helvetica-Bold', fontSize=9.5, leading=12,
        textColor=colors.white, alignment=0)

    wrapped = []
    for i, row in enumerate(rows):
        wrapped_row = []
        for cell in row:
            if isinstance(cell, str):
                style = header_style if (header and i == 0) else cell_style
                wrapped_row.append(Paragraph(cell, style))
            else:
                wrapped_row.append(cell)
        wrapped.append(wrapped_row)

    t = Table(wrapped, colWidths=col_widths)
    style = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, GREY_BORDER),
    ]
    if header:
        style.append(('BACKGROUND', (0, 0), (-1, 0), MAROON))
    t.setStyle(TableStyle(style))
    return t


def callout(title, body, kind='info'):
    palette = {
        'info': (BLUE_INFO, BLUE_LIGHT, 'NOTE'),
        'warn': (ORANGE_WARN, ORANGE_LIGHT, 'IMPORTANT'),
        'ok':   (GREEN_OK, GREEN_LIGHT, 'GUARANTEED'),
    }
    border, bg, label = palette.get(kind, palette['info'])
    title_p = Paragraph(
        f'<font color="{border.hexval()}"><b>{label}</b></font> &nbsp; <b>{title}</b>',
        ParagraphStyle('CT', fontName='Helvetica-Bold', fontSize=10,
                       textColor=MAROON, spaceAfter=4))
    body_p = Paragraph(body,
        ParagraphStyle('CB', fontName='Helvetica', fontSize=9.5,
                       leading=13, textColor=GREY_DARK))
    inner = Table([[title_p], [body_p]], colWidths=['*'])
    inner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LINEBEFORE', (0, 0), (0, -1), 3, border),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([Spacer(1, 6), inner, Spacer(1, 8)])


class PageNum(Canvas):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont('Helvetica', 8.5)
            self.setFillColor(GREY_MID)
            self.drawCentredString(A4[0] / 2, 1.0 * cm,
                f'Page {self._pageNumber} of {total}')
            self.setFont('Helvetica', 8)
            self.drawString(2 * cm, 1.0 * cm,
                'ERP Repair Request Integration')
            self.drawRightString(A4[0] - 2 * cm, 1.0 * cm,
                date.today().strftime('%B %d, %Y'))
            super().showPage()
        super().save()


# ─── Build the document ─────────────────────────────────────────────
story = []

# ─── Cover ──────────────────────────────────────────────────────────
story.append(Spacer(1, 60))
story.append(Paragraph('ERP Repair Request Integration', S['Title']))
story.append(Paragraph('System Flow Document', S['Subtitle']))
story.append(Spacer(1, 20))

cover_meta = [
    ['From:', 'Dispatch Scheduler application'],
    ['To:', 'ERP backend / IT team'],
    ['Purpose:',
     'Establish a one-way, read-only data sync from the ERP Repair Request '
     'module to the Dispatch Scheduler\'s BreakdownLog table.'],
    ['Date prepared:', date.today().strftime('%B %d, %Y')],
    ['Status:', 'Draft for IT review — awaiting service account + refresh token'],
]
cover_meta_rows = [
    [Paragraph(f'<b>{k}</b>', S['Body']), Paragraph(v, S['Body'])]
    for k, v in cover_meta
]
ct = Table(cover_meta_rows, colWidths=[3.6 * cm, 12 * cm], hAlign='CENTER')
ct.setStyle(TableStyle([
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ('TOPPADDING', (0, 0), (-1, -1), 6),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ('LINEBELOW', (0, 0), (-1, -1), 0.4, GREY_BORDER),
]))
story.append(ct)
story.append(Spacer(1, 30))

story.append(callout('What this document is for',
    'A high-level description of how the planned integration will behave: '
    'what gets called, when, how authentication is handled, what data is '
    'pulled, where it lands. Intended to support the IT team\'s decision '
    'on issuing a long-lived service account and refresh token.',
    kind='info'))

story.append(PageBreak())

# ─── Section 1: Overview ────────────────────────────────────────────
story.append(Paragraph('1. Overview', S['H1']))
story.append(Paragraph(
    'The Dispatch Scheduler currently records vehicle breakdowns manually. '
    'The ERP Repair Request module already captures the same information — '
    'often more thoroughly, with multi-stage approvals and per-job-order '
    'progress. This integration mirrors that data into the Dispatch '
    'Scheduler so dispatchers can see plate availability in real time '
    'without redundant data entry.',
    S['BodyJ']))

story.append(Paragraph('Key characteristics', S['H2']))
chars = [
    ['Property', 'Value'],
    ['Direction',      'ERP → Dispatch Scheduler (one-way)'],
    ['Operations',     'GET only — no write/update/delete'],
    ['Authentication', 'Bearer token + 401-triggered refresh-token flow'],
    ['Trigger',        'Cron polling, every 10 minutes (configurable)'],
    ['Volume estimate','~5–10 repair requests per day'],
    ['Calls per day',  '~144 list calls (off-peak distributed)'],
    ['Persistence',    'Local SQLite — BreakdownLog table with new ERP-link columns'],
    ['Failure policy', 'Skip cycle on transient error; alert on persistent 401'],
]
story.append(std_table(chars, col_widths=[4 * cm, 12 * cm]))

story.append(Paragraph('1.1 Architecture diagram', S['H2']))
diagram = '''+-------------------------------+      +-----------------------------------+
|  ERP System                   |      |  Dispatch Scheduler               |
|  erp-api.gainersand.ph        |&lt;-----|  PythonAnywhere (cloud)           |
|                               |HTTPS |                                   |
|  /api/repair-request          |  GET |  - Polling worker (every 10 min)  |
|  /api/repair-request/&lt;id&gt;/show |      |  - Bearer token in .env file      |
|  /api/auth/refresh            |      |  - Read-only access               |
|                               |      |  - Writes to BreakdownLog table   |
+-------------------------------+      +-----------------------------------+
                                                  |
                                                  v
                                       +-----------------------------------+
                                       |  Dispatcher UI / Fleet Manager    |
                                       |  /breakdown page                  |
                                       |  - Sees ERP-synced breakdowns     |
                                       |  - "View in ERP" link per row     |
                                       +-----------------------------------+
'''
story.append(Paragraph(f'<pre>{diagram}</pre>', S['Code']))
story.append(Paragraph(
    'Figure 1: The Dispatch Scheduler app is the sole caller. The ERP API '
    'is never touched by browsers — all calls originate from the '
    'PythonAnywhere backend.',
    S['Caption']))

story.append(PageBreak())

# ─── Section 2: Detailed flow ───────────────────────────────────────
story.append(Paragraph('2. Detailed flow per polling cycle', S['H1']))
story.append(Paragraph(
    'A single iteration of the polling worker. The cycle runs every 10 '
    'minutes via PythonAnywhere\'s scheduled-task feature.',
    S['BodyJ']))

steps = [
    ['#', 'Step', 'Detail'],
    ['1', 'Wake up',
     'Polling worker process started by PA cron. Reads JOBORDERS_TOKEN '
     'and JOBORDERS_REFRESH_TOKEN from the .env file at the project root.'],
    ['2', 'Compute since-timestamp',
     'Looks up the latest BreakdownLog.last_synced_at across all '
     'ERP-linked rows. Falls back to "24 hours ago" on first run.'],
    ['3', 'Call list endpoint',
     'GET /api/repair-request?since=&lt;iso8601&gt;&page=1 with header '
     'Authorization: Bearer &lt;access_token&gt;. Follows pagination if '
     'next-page link is present.'],
    ['4', '401 handling',
     'If response is 401 (token expired): call POST /api/auth/refresh '
     'with the refresh_token, store the new access_token in memory, '
     'retry the list call ONCE. If still 401 → log error, skip cycle.'],
    ['5', 'Parse response',
     'For each repair-request item in data[], compute derived fields:'
     '<br/>• match equipment.ref_no to local Plate.body_no'
     '<br/>• derive status = "Fixed" if all job_orders.progress.total_done '
     '== total_count, else "Under Repair"'
     '<br/>• extract issue description from repair_requests[].issue'],
    ['6', 'Upsert',
     'For each item, find existing BreakdownLog WHERE jo_external_id = '
     'item.id. If found → update fields. If not → INSERT new row. Set '
     'last_synced_at = now().'],
    ['7', 'Optional: trigger UI refresh',
     'Push a tiny "breakdown_updated" event to Firebase Realtime DB '
     '(already wired). Any open browser refreshes the /breakdown page.'],
    ['8', 'Sleep',
     'Worker exits. PA cron will restart it in 10 minutes.'],
]
story.append(std_table(steps, col_widths=[0.7 * cm, 4 * cm, 11.3 * cm]))

story.append(callout('Why polling instead of webhooks',
    'PythonAnywhere\'s outbound network is reliable but inbound webhook '
    'endpoints require additional security review (CSRF, signature '
    'verification, etc.). Polling is simpler to operate and adequate '
    'for the low volume expected (~5–10 records/day). If the team prefers '
    'a webhook approach later, we can add a receive endpoint as a Phase 2 '
    'enhancement.',
    kind='info'))

story.append(PageBreak())

# ─── Section 3: Data mapping ────────────────────────────────────────
story.append(Paragraph('3. Data mapping', S['H1']))
story.append(Paragraph(
    'Each ERP field is mapped to a column on the local BreakdownLog '
    'table. New columns (prefixed with <i>jo_</i> or <i>equipment_</i>) '
    'will be added via a database migration on our side.',
    S['BodyJ']))

mapping = [
    ['ERP field', 'Type', 'Used for', 'Local column'],
    ['id', 'int', 'External link / dedup key', 'jo_external_id (new)'],
    ['ref_no', 'string', 'Truck identifier', 'matches Plate.body_no'],
    ['equipment.name', 'string', 'Display', 'equipment_name (new)'],
    ['equipment.brand', 'string', 'Display', 'equipment_brand (new)'],
    ['operator_name', 'string', 'Driver context', 'operator_name (new)'],
    ['prepared_by', 'string', 'Requester audit', 'requested_by (new)'],
    ['approved_by', 'string', 'Dispatcher approval', 'approved_by_dispatcher (new)'],
    ['maintenance_approved_by', 'string', 'Maintenance approval',
     'approved_by_maintenance (new)'],
    ['repair_requests[].issue',
     'string[]', 'Description (joined)', 'description'],
    ['status_group.* + job_orders[].progress',
     'derived', 'Status mapping', 'status (Active / Fixed)'],
    ['created_at', 'datetime', 'When opened', 'start_at'],
    ['transactions[] (last complete)', 'datetime',
     'When closed', 'end_at'],
    ['(server timestamp)', 'datetime', 'Sync watermark',
     'last_synced_at (new)'],
]
story.append(std_table(mapping, col_widths=[4 * cm, 1.7 * cm, 4.3 * cm, 6 * cm]))

story.append(callout('Plate matching is fuzzy',
    'The link between equipment.ref_no (e.g., "D26E06") and our local '
    'Plate.body_no may not be 1:1. If a ref_no does not match any active '
    'plate, the BreakdownLog row is still created but with plate_id = NULL '
    'and a warning logged. Fleet manager can manually link it via the '
    '/breakdown UI.',
    kind='warn'))

story.append(PageBreak())

# ─── Section 4: Security ────────────────────────────────────────────
story.append(Paragraph('4. Security measures on our side', S['H1']))
story.append(Paragraph(
    'Recently-completed hardening work that protects the credentials '
    'you will share with the Dispatch Scheduler:',
    S['BodyJ']))

sec = [
    ['Concern', 'Mitigation'],
    ['Credential storage',
     'Stored in a .env file at the project root. The file is gitignored '
     '(never enters source control), set to mode 600 (owner-only read), '
     'and lives under the user\'s home directory on PythonAnywhere.'],
    ['Token leak via logs',
     'Token is never logged. HTTP request logs contain only URL and '
     'status code, never the Authorization header value.'],
    ['Token leak via UI',
     'No frontend ever sees the token. All API calls are server-to-server. '
     'Browsers communicate only with the Dispatch Scheduler\'s own routes.'],
    ['SECRET_KEY for our own sessions',
     'Migrated from a hard-coded fallback (visible in public repo) to '
     'a strong random key stored in the same .env file. Application '
     'refuses to start if SECRET_KEY is missing.'],
    ['Session hijacking',
     'Session cookies set with HttpOnly, Secure (HTTPS-only), and '
     'SameSite=Lax flags. 12-hour expiry on inactive sessions.'],
    ['HTTPS termination',
     'PythonAnywhere terminates HTTPS at its front-end proxy. ProxyFix '
     'middleware passes the real scheme to Flask so all generated URLs '
     'and cookie-secure checks behave correctly.'],
    ['SQL injection',
     'All database access through SQLAlchemy ORM with parameterized '
     'queries. No raw concatenated SQL strings.'],
    ['XSS reflection',
     'Jinja2 template engine with auto-escape enabled (default).'],
]
story.append(std_table(sec, col_widths=[4.5 * cm, 11.5 * cm]))

story.append(callout('Already audited and hardened',
    'These items were verified and the missing pieces fixed in the most '
    'recent deployment (May 26, 2026). The Dispatch Scheduler is currently '
    'running with all of the above measures in place.',
    kind='ok'))

story.append(PageBreak())

# ─── Section 5: What we need from IT ────────────────────────────────
story.append(Paragraph('5. What we need from the IT team', S['H1']))
story.append(Paragraph(
    'Three items, in priority order:',
    S['BodyJ']))

needs = [
    ['#', 'Item', 'Notes'],
    ['1', 'Service-account refresh token',
     'A long-lived refresh token issued to a dedicated read-only service '
     'account (NOT a personal user account). The Dispatch Scheduler '
     'will store it in .env and use it to obtain access tokens on demand.'],
    ['2', 'List endpoint URL + supported filters',
     'You confirmed this likely exists already. Need to know: exact path, '
     'supported query params (since / from / to / page / per_page), and '
     'pagination format (next_page_url, cursor, or page-number).'],
    ['3', 'Refresh-token endpoint',
     'The URL and request/response shape for exchanging a refresh token '
     'for a new access token. Standard formats are fine — e.g., POST '
     '/api/auth/refresh with body {refresh_token: "..."} returning '
     '{access_token: "...", expires_in: ...}.'],
]
story.append(std_table(needs, col_widths=[0.7 * cm, 4.8 * cm, 10.5 * cm]))

story.append(Paragraph('5.1 Nice to have (optional)', S['H2']))
nice = [
    ['Item', 'Why it would help'],
    ['Rate-limit ceiling',
     'So we can tune polling cadence to stay safely below it.'],
    ['Historical retention policy',
     'How far back can we backfill on first sync?'],
    ['Webhook capability',
     'A future Phase-2 upgrade to push-based sync, replacing polling.'],
    ['ref_no → equipment list endpoint',
     'To pre-populate a mapping table so plate matching is reliable from '
     'day one.'],
]
story.append(std_table(nice, col_widths=[5 * cm, 11 * cm]))

story.append(PageBreak())

# ─── Section 6: Failure handling ────────────────────────────────────
story.append(Paragraph('6. Failure handling', S['H1']))
story.append(Paragraph(
    'Each failure mode and how the polling worker responds:',
    S['BodyJ']))

failures = [
    ['Failure', 'Worker response'],
    ['Network timeout',
     'Logged. Skip this cycle. Retry on next poll (10 min later).'],
    ['HTTP 401 (token expired)',
     'Call refresh endpoint. Retry the failed call ONCE with the new '
     'token. If still 401 → log persistent auth error and skip cycle. '
     'No infinite refresh loops.'],
    ['HTTP 403 (forbidden)',
     'Permanent error. Logged with full request/response context. '
     'Skip cycle, do not retry. Alerts the IT admin via daily log review.'],
    ['HTTP 5xx (server error)',
     'Likely transient. Log + skip cycle. Retry next poll.'],
    ['Malformed JSON response',
     'Log + skip cycle. Do not crash the worker.'],
    ['equipment.ref_no does not match any local Plate',
     'BreakdownLog row created with plate_id=NULL. Logged as warning. '
     'Fleet manager links it manually via the UI.'],
    ['.env missing JOBORDERS_TOKEN at startup',
     'Application refuses to start (fail-fast pattern). Forces operator '
     'to set the env var before the app can run.'],
    ['ERP returns unexpected status field shape',
     'Falls back to "Under Repair" as a safe default. Logged for review.'],
    ['Polling worker process crash',
     'PythonAnywhere always-on task auto-restarts on crash. Polling '
     'resumes within 1 minute. No manual intervention required.'],
]
story.append(std_table(failures, col_widths=[5.5 * cm, 10.5 * cm]))

story.append(Paragraph('6.1 Monitoring on our side', S['H2']))
for x in [
    'Polling worker writes a single-line summary to its log on every cycle '
    '(records pulled, upserts, errors). PA preserves the last few days.',
    'Daily review of error rate is part of operations.',
    'If repeated 401s are seen, IT will be contacted with timestamps and '
    'sample request IDs (if your API returns them in headers).',
]:
    story.append(Paragraph(f'•  {x}', S['Body']))

story.append(PageBreak())

# ─── Section 7: Timeline ────────────────────────────────────────────
story.append(Paragraph('7. Estimated timeline', S['H1']))
tl = [
    ['Phase', 'Estimated effort', 'Dependency'],
    ['Receive service-account token + endpoint docs from IT',
     '— (your side)', '—'],
    ['Build joborders_client.py + sync worker',
     '4–6 hours', 'Step 1 complete'],
    ['Database migration (new BreakdownLog columns)',
     '30 min', 'Above'],
    ['UI tweaks on /breakdown page',
     '2 hours', 'Above'],
    ['Smoke test on staging (one polling cycle)',
     '1 hour', 'Above'],
    ['Production deploy to PythonAnywhere',
     '30 min', 'Smoke test passed'],
    ['Monitor for 1 week',
     '— (passive)', 'Production deployed'],
]
story.append(std_table(tl, col_widths=[7 * cm, 4 * cm, 5 * cm]))

story.append(Spacer(1, 20))
story.append(callout('Next step',
    'Please review this document at your convenience. If the approach '
    'looks acceptable, share back the three items in section 5 (service '
    'token, list endpoint, refresh endpoint) and I will start the '
    'implementation right away. Happy to discuss any concerns or '
    'adjustments before you commit.',
    kind='ok'))

# ─── Build ──────────────────────────────────────────────────────────
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', 'ERP_INTEGRATION_SYSTEM_FLOW.pdf')
out_path = os.path.abspath(out_path)

doc = SimpleDocTemplate(out_path, pagesize=A4,
    leftMargin=2 * cm, rightMargin=2 * cm,
    topMargin=2.2 * cm, bottomMargin=1.8 * cm,
    title='ERP Repair Request Integration — System Flow',
    author='Dispatch Scheduler Team')

doc.build(story, canvasmaker=PageNum)

size_kb = os.path.getsize(out_path) / 1024
print(f'OK  Generated: {out_path}')
print(f'    Size: {size_kb:,.1f} KB')
