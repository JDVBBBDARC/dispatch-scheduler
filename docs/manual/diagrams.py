"""ReportLab Drawing-based diagrams for the manual — replace placeholder
boxes for architecture and topology figures.

Returns reportlab.graphics.shapes.Drawing objects which can be embedded
directly in a Platypus story.
"""
from reportlab.graphics.shapes import (Drawing, Rect, String, Line,
                                         Polygon, Group)
from reportlab.lib.units import cm
from reportlab.lib import colors

from styles import (MAROON, MAROON_LIGHT, GREY_DARK, GREY_MID,
                     GREY_BORDER, GREY_LIGHT, BLUE_INFO, BLUE_LIGHT,
                     GREEN_OK, GREEN_LIGHT, ORANGE_WARN, ORANGE_LIGHT)


def _box(x, y, w, h, label_top, label_bottom='', fill=MAROON_LIGHT,
         stroke=MAROON, label_color=MAROON, secondary_color=GREY_DARK):
    """One labelled rectangle box. Returns a Group of shapes."""
    g = Group()
    g.add(Rect(x, y, w, h, fillColor=fill, strokeColor=stroke,
               strokeWidth=1.2, rx=4, ry=4))
    g.add(String(x + w / 2, y + h - 16, label_top,
                  fontName='Helvetica-Bold', fontSize=10,
                  fillColor=label_color, textAnchor='middle'))
    if label_bottom:
        for i, line in enumerate(label_bottom.split('\n')):
            g.add(String(x + w / 2, y + h - 32 - 11 * i, line,
                          fontName='Helvetica', fontSize=8.5,
                          fillColor=secondary_color, textAnchor='middle'))
    return g


def _arrow(x1, y1, x2, y2, label='', color=GREY_DARK):
    """Single-direction arrow with optional label at midpoint."""
    g = Group()
    g.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.4))
    # Arrowhead — small triangle at (x2, y2)
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    head = 6
    hx1 = x2 - head * math.cos(angle - 0.4)
    hy1 = y2 - head * math.sin(angle - 0.4)
    hx2 = x2 - head * math.cos(angle + 0.4)
    hy2 = y2 - head * math.sin(angle + 0.4)
    g.add(Polygon([x2, y2, hx1, hy1, hx2, hy2],
                   fillColor=color, strokeColor=color))
    if label:
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2 + 6
        g.add(String(mid_x, mid_y, label, fontName='Helvetica-Oblique',
                      fontSize=7.5, fillColor=GREY_MID, textAnchor='middle'))
    return g


def _bidir_arrow(x1, y1, x2, y2, label='', color=GREY_DARK):
    """Bidirectional arrow."""
    g = Group()
    g.add(_arrow(x1, y1, x2, y2, '', color))
    g.add(_arrow(x2, y2, x1, y1, '', color))
    if label:
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2 + 8
        g.add(String(mid_x, mid_y, label, fontName='Helvetica-Oblique',
                      fontSize=7.5, fillColor=GREY_MID, textAnchor='middle'))
    return g


def architecture_diagram():
    """High-level system architecture: browser → Flask → SQLite + Cartrack
    API. Used in Section A.3.

    Width is exactly 16 cm to fit the printable area (page = 21 cm A4
    minus 2x2 cm margins = 17 cm available; we leave a hair of margin).
    All shape coordinates are in points (1 cm = 28.346 pt), so the
    drawing canvas is approximately 453 x 198 pt."""
    w, h = 16 * cm, 7 * cm           # 453.5 x 198.4 pt
    d = Drawing(w, h)

    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor('#FAFAFA'),
               strokeColor=colors.transparent))

    # Layout (all in points). Columns + their widths:
    #   col1  x=8,   w=95    Browser
    #   col2  x=120, w=210   PA container (Flask + Worker, side by side)
    #   col3  x=345, w=100   DB and Cartrack stacked
    BR_X, BR_W = 8, 95
    PA_X, PA_W = 120, 210
    R_X,  R_W  = 345, 100

    # ── Tier 1 — Browser ───────────────────────────────────────────────
    d.add(_box(BR_X, h - 75, BR_W, 55,
                'Web Browser',
                'Dispatchers,\nSupervisors,\nManagement',
                fill=BLUE_LIGHT, stroke=BLUE_INFO,
                label_color=BLUE_INFO))

    # ── Tier 2 — PA Container with Flask + Worker ──────────────────────
    d.add(Rect(PA_X, h - 130, PA_W, 110, fillColor=colors.white,
                strokeColor=MAROON, strokeWidth=0.8,
                strokeDashArray=[3, 2], rx=4, ry=4))
    d.add(String(PA_X + PA_W / 2, h - 17,
                  'PythonAnywhere Host',
                  fontName='Helvetica-Oblique', fontSize=8.5,
                  fillColor=MAROON, textAnchor='middle'))
    d.add(_box(PA_X + 10, h - 85, 90, 50,
                'Flask Web App',
                'WSGI server\nSession auth',
                fill=MAROON_LIGHT, stroke=MAROON))
    d.add(_box(PA_X + 110, h - 85, 90, 50,
                'Polling Worker',
                'Always-on task\ncartrack_poll.py',
                fill=ORANGE_LIGHT, stroke=ORANGE_WARN,
                label_color=ORANGE_WARN))

    # ── Tier 3 — DB + Cartrack stacked ────────────────────────────────
    d.add(_box(R_X, h - 75, R_W, 55,
                'SQLite DB',
                'Trips, Plates,\nGPS state,\nGeofences',
                fill=GREEN_LIGHT, stroke=GREEN_OK,
                label_color=GREEN_OK))
    d.add(_box(R_X, h - 175, R_W, 55,
                'Cartrack API',
                'Fleet REST API\n(external)',
                fill=GREY_LIGHT, stroke=GREY_MID,
                label_color=GREY_DARK))

    # ── Arrows ────────────────────────────────────────────────────────
    # Browser ↔ Flask
    d.add(_bidir_arrow(BR_X + BR_W, h - 47,
                        PA_X + 10, h - 60,
                        'HTTPS', color=BLUE_INFO))
    # Flask ↔ DB (over the top, short)
    d.add(_bidir_arrow(PA_X + 100, h - 60,
                        R_X, h - 47,
                        'SQL', color=GREEN_OK))
    # Worker → Cartrack (orange, single-headed for emphasis, then return)
    d.add(_arrow(PA_X + 200, h - 80,
                  R_X, h - 150,
                  'GPS poll (60s)', color=ORANGE_WARN))
    d.add(_arrow(R_X, h - 150,
                  PA_X + 200, h - 90,
                  '', color=ORANGE_WARN))

    return d


def deployment_topology_diagram():
    """Deployment topology with explicit PA host boundary — Section E.1.

    Same width budget as the architecture diagram: 16 cm = ~453 pt.
    Layout: User Device on the left, PA host container in the centre,
    external services stacked on the right."""
    w, h = 16 * cm, 8 * cm           # 453.5 x 226.8 pt
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor('#FAFAFA'),
               strokeColor=colors.transparent))

    # Layout columns:
    #   col1  x=8,   w=90    User Device
    #   col2  x=110, w=235   PA container with 3 components inside
    #   col3  x=355, w=95    External services stacked
    UD_X, UD_W = 8, 90
    PA_X, PA_Y, PA_W, PA_H = 110, 25, 235, 155
    EX_X, EX_W = 355, 95

    # ── User device ────────────────────────────────────────────────────
    d.add(_box(UD_X, h - 95, UD_W, 70,
                'User Device',
                'Browser session\nover HTTPS',
                fill=BLUE_LIGHT, stroke=BLUE_INFO,
                label_color=BLUE_INFO))

    # ── PythonAnywhere host container ──────────────────────────────────
    d.add(Rect(PA_X, PA_Y, PA_W, PA_H, fillColor=colors.white,
                strokeColor=MAROON, strokeWidth=1.2,
                strokeDashArray=[4, 2], rx=6, ry=6))
    d.add(String(PA_X + PA_W / 2, PA_Y + PA_H + 8,
                  'PythonAnywhere — Production Host',
                  fontName='Helvetica-Bold', fontSize=9,
                  fillColor=MAROON, textAnchor='middle'))

    # Flask web app — top-left inside container
    d.add(_box(PA_X + 10, PA_Y + PA_H - 65, 100, 55,
                'Flask Web App',
                'WSGI server\nRoutes + Auth',
                fill=MAROON_LIGHT, stroke=MAROON))
    # Polling worker — top-right inside container
    d.add(_box(PA_X + 125, PA_Y + PA_H - 65, 100, 55,
                'Polling Worker',
                'Always-on task\nGPS ingest',
                fill=ORANGE_LIGHT, stroke=ORANGE_WARN,
                label_color=ORANGE_WARN))
    # Database — centred bottom inside container
    d.add(_box(PA_X + 67, PA_Y + 12, 100, 55,
                'SQLite DB',
                'dispatch.db\n(file-backed)',
                fill=GREEN_LIGHT, stroke=GREEN_OK,
                label_color=GREEN_OK))

    # Internal arrows: each process ↔ DB
    d.add(_bidir_arrow(PA_X + 60, PA_Y + PA_H - 67,
                        PA_X + 95, PA_Y + 67,
                        'read/write', color=GREEN_OK))
    d.add(_bidir_arrow(PA_X + 175, PA_Y + PA_H - 67,
                        PA_X + 140, PA_Y + 67,
                        'read/write', color=GREEN_OK))

    # ── External services ─────────────────────────────────────────────
    d.add(_box(EX_X, PA_Y + PA_H - 70, EX_W, 55,
                'Cartrack API',
                'fleetapi-ph\nREST + Basic',
                fill=GREY_LIGHT, stroke=GREY_MID,
                label_color=GREY_DARK))
    d.add(_box(EX_X, PA_Y + 12, EX_W, 55,
                'Google Sheets',
                'Apps Script\nwebhook',
                fill=GREY_LIGHT, stroke=GREY_MID,
                label_color=GREY_DARK))

    # Arrows out of the host to external services
    d.add(_bidir_arrow(PA_X + 225, PA_Y + PA_H - 45,
                        EX_X, PA_Y + PA_H - 45,
                        'GPS poll', color=ORANGE_WARN))
    d.add(_arrow(PA_X + 165, PA_Y + 35,
                  EX_X, PA_Y + 40,
                  'sync', color=MAROON))

    # User Device ↔ Flask arrow
    d.add(_bidir_arrow(UD_X + UD_W, h - 60,
                        PA_X + 10, PA_Y + PA_H - 38,
                        'HTTPS', color=BLUE_INFO))

    return d
