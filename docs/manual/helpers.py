"""Reusable flowable factories — callout boxes, tables, screenshot
placeholders, SOP frames. Imported by content sections.
"""
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import (Paragraph, Spacer, Table, TableStyle,
                                 KeepInFrame, KeepTogether, PageBreak, Image)
from reportlab.lib.styles import ParagraphStyle

from styles import (build_styles, MAROON, MAROON_LIGHT, BLUE_INFO, BLUE_LIGHT,
                     ORANGE_WARN, ORANGE_LIGHT, GREEN_OK, GREEN_LIGHT,
                     GREY_DARK, GREY_LIGHT, GREY_BORDER, GREY_MID, PAGE_SIZE,
                     MARGIN_LEFT, MARGIN_RIGHT)

S = build_styles()


def h_section(text):
    """Top-of-section title (e.g., 'Section A — System Overview')."""
    return Paragraph(text, S['SectionTitle'])

def h1(text):
    return Paragraph(text, S['H1'])

def h2(text):
    return Paragraph(text, S['H2'])

def h3(text):
    return Paragraph(text, S['H3'])

def p(text):
    return Paragraph(text, S['Body'])

def pj(text):
    return Paragraph(text, S['BodyJ'])

def lead(text):
    return Paragraph(text, S['Lead'])

def caption(text):
    return Paragraph(text, S['Caption'])

def code(text):
    """Code/command-line block. Escape <, > for ReportLab XML parser."""
    safe = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return Paragraph(f'<font face="Courier">{safe}</font>', S['Code'])

def sp(h=8):
    return Spacer(1, h)


def bullet_list(items):
    """Render a list of strings as a styled bullet list."""
    return [Paragraph(f'• {it}', S['Body']) for it in items]


def numbered_list(items, start=1):
    """Render a list of strings as a numbered list."""
    out = []
    for i, it in enumerate(items, start=start):
        out.append(Paragraph(f'<b>{i}.</b> {it}', S['Body']))
    return out


def callout(title, body, kind='info'):
    """Coloured callout box used for cross-references, warnings, and
    procedure notes. `kind` ∈ {info, warn, ok, note}. Returns a single
    Flowable wrapped in KeepTogether so it never splits across pages.

    Note: 'iso' is kept as a back-compat alias for 'note' so older
    section files that still pass kind='iso' don't break — but the
    rendered label is generic ('REFERENCE')."""
    palette = {
        'info': (BLUE_INFO,    BLUE_LIGHT,    'INFO'),
        'warn': (ORANGE_WARN,  ORANGE_LIGHT,  'IMPORTANT'),
        'ok':   (GREEN_OK,     GREEN_LIGHT,   'BEST PRACTICE'),
        'note': (MAROON,       MAROON_LIGHT,  'REFERENCE'),
        'iso':  (MAROON,       MAROON_LIGHT,  'REFERENCE'),  # back-compat alias
    }
    border, bg, label = palette.get(kind, palette['info'])

    title_p = Paragraph(f'<font color="{border.hexval()}"><b>{label}</b></font>'
                        f' &nbsp; <b>{title}</b>', S['CalloutTitle'])
    body_p  = Paragraph(body, S['CalloutBody'])

    inner = [[title_p], [body_p]]
    inner_tbl = Table(inner, colWidths=['*'])
    inner_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LINEBEFORE', (0, 0), (0, -1), 3, border),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 1), (-1, 1), 4),
    ]))
    return KeepTogether([sp(6), inner_tbl, sp(8)])


_SCREENSHOTS_DIR = None
def _get_screenshots_dir():
    """Find the screenshots/ directory relative to this file."""
    global _SCREENSHOTS_DIR
    if _SCREENSHOTS_DIR is None:
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        _SCREENSHOTS_DIR = os.path.join(here, 'screenshots')
    return _SCREENSHOTS_DIR


def screenshot_placeholder(label, height_cm=8, image=None, max_width_cm=15.5):
    """Embed a real screenshot if `image` (filename in screenshots/) is
    provided and exists; otherwise render a bordered placeholder box.

    Returns a single KeepTogether Flowable so the box + caption stay
    on one page.
    """
    import os
    if image:
        path = os.path.join(_get_screenshots_dir(), image)
        if os.path.exists(path):
            try:
                # Image auto-scales when only one dimension given; we
                # use width-bound to fit the printable area cleanly.
                img = Image(path, width=max_width_cm * cm,
                                  height=height_cm * cm,
                                  kind='proportional')
                # Wrap in a Table to give it a subtle border, matching
                # the look of the placeholder boxes.
                tbl = Table([[img]], colWidths=[max_width_cm * cm])
                tbl.setStyle(TableStyle([
                    ('BOX', (0, 0), (-1, -1), 0.7, GREY_BORDER),
                    ('LEFTPADDING',  (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                    ('TOPPADDING',   (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
                    ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                return KeepTogether([sp(4), tbl,
                                      caption(f'Figure: {label}')])
            except Exception as e:
                # Fall through to placeholder if image fails to load.
                pass

    # No image — render the placeholder.
    content = Paragraph(
        f'<font color="#999999"><b>[ INSERT SCREENSHOT ]</b></font><br/>'
        f'<font color="#666666">{label}</font>',
        ParagraphStyle('SS', fontName='Helvetica', fontSize=10,
                       alignment=1, textColor=GREY_MID, leading=14))
    tbl = Table([[content]],
                colWidths=[max_width_cm * cm],
                rowHeights=[height_cm * cm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FAFAFA')),
        ('BOX', (0, 0), (-1, -1), 1.2, GREY_BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    return KeepTogether([sp(4), tbl, caption(f'Figure: {label}')])


def _wrap_cell(val, style):
    """Wrap a cell value in a Paragraph so it word-wraps inside its
    column. Already-Flowable values (Paragraph, Image, Table) pass
    through unchanged."""
    if val is None:
        return ''
    # Anything that already has a wrap() method is a Flowable — leave it.
    if hasattr(val, 'wrap'):
        return val
    s = str(val)
    # ReportLab Paragraph treats < and > as XML; we want literal display
    # unless the source already contains intentional tags like <b>.
    # Heuristic: if the string contains any of our known tags, pass
    # through; otherwise escape <, > to entities.
    known_tags = ('<b>', '</b>', '<i>', '</i>', '<font ', '<br/>',
                  '<u>', '</u>', '<sub>', '</sub>', '<super>', '</super>')
    if not any(t in s for t in known_tags):
        s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return Paragraph(s, style)


def std_table(data, col_widths=None, header_bg=MAROON, header_fg=colors.white,
              row_height=None, zebra=True, header_rows=1):
    """Standard 2-column-or-more table with maroon header band, zebra
    striping, and grey borders. Auto-wraps string cells in Paragraphs
    so text word-wraps inside its column instead of overflowing."""
    n_cols = max(len(r) for r in data)
    if col_widths is None:
        avail = PAGE_SIZE[0] - MARGIN_LEFT - MARGIN_RIGHT
        col_widths = [avail / n_cols] * n_cols

    # Cell paragraph styles — different for header rows vs body rows.
    header_style = ParagraphStyle(
        'CellHeader', fontName='Helvetica-Bold', fontSize=9.5,
        leading=12, textColor=colors.white, alignment=0)
    body_style = ParagraphStyle(
        'CellBody', fontName='Helvetica', fontSize=9,
        leading=12, textColor=GREY_DARK, alignment=0)

    # Wrap every cell in a Paragraph for proper word-wrap.
    wrapped = []
    for r_idx, row in enumerate(data):
        is_header = r_idx < header_rows
        style = header_style if is_header else body_style
        wrapped.append([_wrap_cell(c, style) for c in row])

    tbl = Table(wrapped, colWidths=col_widths, repeatRows=header_rows)
    style = [
        ('BACKGROUND', (0, 0), (-1, header_rows - 1), header_bg),
        ('TEXTCOLOR',  (0, 0), (-1, header_rows - 1), header_fg),
        ('FONTNAME',   (0, 0), (-1, header_rows - 1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, header_rows - 1), 9.5),
        ('ALIGN',      (0, 0), (-1, header_rows - 1), 'LEFT'),
        ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE',   (0, header_rows), (-1, -1), 9),
        ('FONTNAME',   (0, header_rows), (-1, -1), 'Helvetica'),
        ('TEXTCOLOR',  (0, header_rows), (-1, -1), GREY_DARK),
        ('BOX',        (0, 0), (-1, -1), 0.5, GREY_BORDER),
        ('INNERGRID',  (0, 0), (-1, -1), 0.3, GREY_BORDER),
        ('LEFTPADDING',  (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING',   (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
    ]
    if zebra:
        for r in range(header_rows, len(data)):
            if (r - header_rows) % 2 == 1:
                style.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#F8F9FA')))
    tbl.setStyle(TableStyle(style))
    return tbl


def sop_box(sop_id, title, purpose, scope, responsibilities, procedure,
            records, frequency, references):
    """Render a complete procedure block — Purpose, Scope, Responsibilities,
    Procedure, Records, Frequency, References. Always starts on a new
    page so each procedure can be printed or shared independently.

    Field labels render in MAROON bold against a tinted background so
    they're clearly visible on the body row (previously they were
    rendered white-on-white and invisible)."""
    out = []
    out.append(PageBreak())
    out.append(Paragraph(f'<font color="{MAROON.hexval()}"><b>SOP-{sop_id}</b></font>',
                          ParagraphStyle('SOPID', fontName='Helvetica-Bold',
                                         fontSize=12, textColor=MAROON,
                                         spaceAfter=4)))
    out.append(Paragraph(title, S['H1']))

    fields = [
        ('Purpose',          purpose),
        ('Scope',            scope),
        ('Responsibilities', responsibilities),
        ('Procedure',        procedure),
        ('Records Generated',records),
        ('Frequency',        frequency),
        ('References',       references),
    ]
    # Bypass std_table's auto-wrap for this table because we want a
    # custom tinted background on the Field column and full control
    # over the label styling. Pre-wrap cells manually.
    label_style = ParagraphStyle(
        'SOPFieldLabel', fontName='Helvetica-Bold',
        fontSize=9.5, leading=13, textColor=MAROON, alignment=0)
    body_style = ParagraphStyle(
        'SOPFieldBody', fontName='Helvetica',
        fontSize=9, leading=13, textColor=GREY_DARK, alignment=0)
    header_label_style = ParagraphStyle(
        'SOPFieldHdr', fontName='Helvetica-Bold',
        fontSize=9.5, leading=12, textColor=colors.white, alignment=0)

    rows = [[Paragraph('Field', header_label_style),
             Paragraph('Description', header_label_style)]]
    for label, val in fields:
        if isinstance(val, list):
            val_html = '<br/>'.join(f'{i+1}. {v}' for i, v in enumerate(val))
        else:
            val_html = val
        rows.append([
            Paragraph(label, label_style),
            Paragraph(val_html, body_style),
        ])

    tbl = Table(rows, colWidths=[4 * cm, 12.5 * cm], repeatRows=1)
    tbl.setStyle(TableStyle([
        # Header band — maroon with white text
        ('BACKGROUND',   (0, 0), (-1, 0), MAROON),
        # Field-column tint — soft maroon so labels pop without being harsh
        ('BACKGROUND',   (0, 1), (0, -1), MAROON_LIGHT),
        # Body cells — clean white
        ('BACKGROUND',   (1, 1), (1, -1), colors.white),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('BOX',          (0, 0), (-1, -1), 0.5, GREY_BORDER),
        ('INNERGRID',    (0, 0), (-1, -1), 0.3, GREY_BORDER),
        ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING',   (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 7),
    ]))
    out.append(tbl)
    out.append(sp(10))
    return out
