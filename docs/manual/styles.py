"""Custom paragraph styles + page templates for the Dispatch Scheduler
System Manual. Imported by generate.py.

Design goals:
- Clean Helvetica, sober colors, lots of whitespace
- Every page has a header (doc id) and footer (page X of Y)
- Section dividers use a maroon accent color matching the app's UI
- Callout boxes for procedures, warnings, and notes
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import PageTemplate, Frame, BaseDocTemplate
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfgen.canvas import Canvas

# ── Document constants ────────────────────────────────────────────────
# COMPANY_NAME is retained as an import target for back-compat with the
# front matter; it now resolves to a generic placeholder. Re-skin per
# deployment by editing this single line.
COMPANY_NAME   = 'Dispatch Operations'
DOC_TITLE      = 'Dispatch Scheduler System Manual'
DOC_ID         = 'DSM-001'
DOC_VERSION    = '1.3'
DOC_DATE       = 'June 2026'
PAGE_SIZE      = A4

# ── Brand palette ─────────────────────────────────────────────────────
MAROON         = colors.HexColor('#8B1A2B')   # primary brand (matches app)
MAROON_LIGHT   = colors.HexColor('#F5E6E8')
GREY_DARK      = colors.HexColor('#2C3E50')
GREY_MID       = colors.HexColor('#7F8C8D')
GREY_LIGHT     = colors.HexColor('#ECEFF1')
GREY_BORDER    = colors.HexColor('#D5DBDB')
BLUE_INFO      = colors.HexColor('#2980B9')
BLUE_LIGHT     = colors.HexColor('#EBF5FB')
ORANGE_WARN    = colors.HexColor('#D35400')
ORANGE_LIGHT   = colors.HexColor('#FDF2E9')
GREEN_OK       = colors.HexColor('#27AE60')
GREEN_LIGHT    = colors.HexColor('#E8F8F0')

# ── Page layout ───────────────────────────────────────────────────────
MARGIN_LEFT    = 2.0 * cm
MARGIN_RIGHT   = 2.0 * cm
MARGIN_TOP     = 2.5 * cm
MARGIN_BOTTOM  = 2.5 * cm


def build_styles():
    """Return a dict of named ParagraphStyles used across the document."""
    base = getSampleStyleSheet()
    S = {}

    # Body text — default
    S['Body'] = ParagraphStyle(
        'Body', parent=base['BodyText'],
        fontName='Helvetica', fontSize=10, leading=14,
        textColor=GREY_DARK, spaceAfter=6, alignment=0,
    )
    # Body justified (for long paragraphs)
    S['BodyJ'] = ParagraphStyle(
        'BodyJ', parent=S['Body'], alignment=4,   # 4 = justify
    )
    # Lead paragraph (slightly larger, used after section titles)
    S['Lead'] = ParagraphStyle(
        'Lead', parent=S['Body'], fontSize=11, leading=16,
        textColor=GREY_DARK, spaceAfter=10,
    )
    # Section title (e.g., "Section A — System Overview")
    S['SectionTitle'] = ParagraphStyle(
        'SectionTitle', parent=base['Heading1'],
        fontName='Helvetica-Bold', fontSize=22, leading=28,
        textColor=MAROON, spaceBefore=0, spaceAfter=18, alignment=0,
    )
    # H1 — chapter heading inside a section (e.g., "A.1 Purpose & Scope")
    S['H1'] = ParagraphStyle(
        'H1', parent=base['Heading1'],
        fontName='Helvetica-Bold', fontSize=16, leading=20,
        textColor=MAROON, spaceBefore=20, spaceAfter=10,
        keepWithNext=1, borderPadding=0,
    )
    # H2 — subsection heading
    S['H2'] = ParagraphStyle(
        'H2', parent=base['Heading2'],
        fontName='Helvetica-Bold', fontSize=12.5, leading=16,
        textColor=GREY_DARK, spaceBefore=12, spaceAfter=6, keepWithNext=1,
    )
    # H3 — minor heading
    S['H3'] = ParagraphStyle(
        'H3', parent=base['Heading3'],
        fontName='Helvetica-Bold', fontSize=10.5, leading=14,
        textColor=GREY_DARK, spaceBefore=8, spaceAfter=4, keepWithNext=1,
    )
    # Cover page huge title
    S['CoverTitle'] = ParagraphStyle(
        'CoverTitle', parent=base['Title'],
        fontName='Helvetica-Bold', fontSize=32, leading=40,
        textColor=MAROON, alignment=1, spaceAfter=20,
    )
    # Cover page subtitle
    S['CoverSub'] = ParagraphStyle(
        'CoverSub', parent=base['Normal'],
        fontName='Helvetica', fontSize=16, leading=22,
        textColor=GREY_DARK, alignment=1, spaceAfter=8,
    )
    # Cover page small metadata
    S['CoverMeta'] = ParagraphStyle(
        'CoverMeta', parent=base['Normal'],
        fontName='Helvetica', fontSize=11, leading=15,
        textColor=GREY_MID, alignment=1, spaceAfter=4,
    )
    # Caption — for figures, screenshots, tables
    S['Caption'] = ParagraphStyle(
        'Caption', parent=S['Body'], fontSize=9, leading=12,
        textColor=GREY_MID, alignment=1, spaceBefore=4, spaceAfter=12,
    )
    # Code / monospace — for command lines, API endpoints
    S['Code'] = ParagraphStyle(
        'Code', parent=S['Body'], fontName='Courier',
        fontSize=9, leading=12, leftIndent=12,
        backColor=GREY_LIGHT, borderPadding=6,
    )
    # Cross-reference — italic, small, used for "see also" style refs.
    S['ClauseRef'] = ParagraphStyle(
        'ClauseRef', parent=S['Body'], fontName='Helvetica-Oblique',
        fontSize=9, textColor=BLUE_INFO, spaceAfter=4,
    )
    # Callout box body styles (used inside Table/KeepInFrame wrappers)
    S['CalloutBody'] = ParagraphStyle(
        'CalloutBody', parent=S['Body'], fontSize=9.5, leading=13,
        textColor=GREY_DARK, spaceAfter=0,
    )
    S['CalloutTitle'] = ParagraphStyle(
        'CalloutTitle', parent=S['Body'], fontName='Helvetica-Bold',
        fontSize=10, leading=12, textColor=MAROON, spaceAfter=4,
    )
    # TOC entries (3 levels)
    S['TOC1'] = ParagraphStyle(
        'TOC1', fontName='Helvetica-Bold', fontSize=11, leading=18,
        textColor=MAROON, leftIndent=0, spaceBefore=6,
    )
    S['TOC2'] = ParagraphStyle(
        'TOC2', fontName='Helvetica', fontSize=10, leading=14,
        textColor=GREY_DARK, leftIndent=18,
    )
    S['TOC3'] = ParagraphStyle(
        'TOC3', fontName='Helvetica', fontSize=9.5, leading=13,
        textColor=GREY_MID, leftIndent=36,
    )

    return S


# ── Page numbering canvas ─────────────────────────────────────────────
class NumberedCanvas(Canvas):
    """Two-pass canvas that knows the total page count when drawing
    each page footer. Enables "Page X of Y" numbering."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_states = []

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            self._draw_page_chrome(total)
            super().showPage()
        super().save()

    def _draw_page_chrome(self, total_pages):
        """Header + footer drawn on every page except the cover."""
        page_num = self._pageNumber
        # Skip chrome on cover page
        if page_num == 1:
            return

        w, h = PAGE_SIZE

        # ── Header ─────────────────────────────────────────────────────
        self.setFont('Helvetica-Bold', 9)
        self.setFillColor(MAROON)
        self.drawString(MARGIN_LEFT, h - 1.4 * cm, COMPANY_NAME)
        self.setFont('Helvetica', 8.5)
        self.setFillColor(GREY_MID)
        self.drawRightString(w - MARGIN_RIGHT, h - 1.4 * cm,
                             f'{DOC_TITLE}   |   {DOC_ID}')
        # Header rule
        self.setStrokeColor(MAROON)
        self.setLineWidth(0.6)
        self.line(MARGIN_LEFT, h - 1.7 * cm,
                  w - MARGIN_RIGHT, h - 1.7 * cm)

        # ── Footer ─────────────────────────────────────────────────────
        self.setStrokeColor(GREY_BORDER)
        self.setLineWidth(0.4)
        self.line(MARGIN_LEFT, 1.7 * cm,
                  w - MARGIN_RIGHT, 1.7 * cm)
        self.setFont('Helvetica', 8.5)
        self.setFillColor(GREY_MID)
        # Left footer: doc version + date
        self.drawString(MARGIN_LEFT, 1.2 * cm,
                        f'Version {DOC_VERSION}  |  {DOC_DATE}')
        # Center footer: classification
        self.drawCentredString(w / 2.0, 1.2 * cm,
                               'Controlled Document — Internal Use')
        # Right footer: page number
        self.drawRightString(w - MARGIN_RIGHT, 1.2 * cm,
                             f'Page {page_num} of {total_pages}')


# ── Document template ─────────────────────────────────────────────────
class ManualDocTemplate(BaseDocTemplate):
    """Custom BaseDocTemplate with one frame per page and TOC support."""

    def __init__(self, filename, **kwargs):
        super().__init__(filename, pagesize=PAGE_SIZE,
                         leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
                         topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
                         title=DOC_TITLE, author=COMPANY_NAME,
                         subject='Dispatch Scheduler System Manual',
                         **kwargs)

        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height,
                      id='normal', showBoundary=0)
        template = PageTemplate(id='main', frames=[frame])
        self.addPageTemplates([template])

    def afterFlowable(self, flowable):
        """Register heading flowables with the TOC."""
        if not hasattr(flowable, 'getPlainText'):
            return
        style = getattr(flowable, 'style', None)
        if style is None:
            return
        text = flowable.getPlainText()
        name = style.name
        if name == 'SectionTitle':
            self.notify('TOCEntry', (0, text, self.page))
        elif name == 'H1':
            self.notify('TOCEntry', (1, text, self.page))
        elif name == 'H2':
            self.notify('TOCEntry', (2, text, self.page))


def make_toc():
    """Configured TableOfContents flowable used in the front matter."""
    S = build_styles()
    toc = TableOfContents()
    toc.levelStyles = [S['TOC1'], S['TOC2'], S['TOC3']]
    return toc
