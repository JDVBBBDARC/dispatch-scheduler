"""Main entry point — assembles all sections and renders the PDF.

Run from the project root:
    python docs/manual/generate.py
Output:
    DISPATCH_SCHEDULER_SYSTEM_MANUAL_v1.0.pdf
"""
import os
import sys
from pathlib import Path

# Make sibling modules importable when run as a script.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from styles import ManualDocTemplate, make_toc, DOC_VERSION
from front_matter import (cover_page, document_control_page, toc_page,
                           glossary_page)
from section_a   import section_a
from section_b   import section_b
from section_c   import section_c
from section_def import section_d, section_e, section_f


def build():
    project_root = HERE.parent.parent
    out_path = project_root / f'DISPATCH_SCHEDULER_SYSTEM_MANUAL_v{DOC_VERSION}.pdf'

    # If the target file is locked by an open PDF viewer (Foxit, Acrobat),
    # write to a numbered fallback so the build doesn't fail.
    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            i = 2
            while True:
                alt = out_path.with_name(
                    f'DISPATCH_SCHEDULER_SYSTEM_MANUAL_v{DOC_VERSION}_r{i}.pdf')
                if not alt.exists():
                    out_path = alt
                    print(f'(target locked — writing to {alt.name} instead)')
                    break
                i += 1

    doc = ManualDocTemplate(str(out_path))
    toc = make_toc()

    story = []
    # Front matter (no PageBreak before cover — first page is cover).
    story.extend(cover_page())
    story.extend(document_control_page())
    story.extend(toc_page(toc))
    story.extend(glossary_page())

    # Main body
    story.extend(section_a())
    story.extend(section_b())
    story.extend(section_c())
    story.extend(section_d())
    story.extend(section_e())
    story.extend(section_f())

    # multiBuild does the two-pass render needed for the TOC and for
    # the "Page X of Y" footer numbering.
    from styles import NumberedCanvas
    doc.multiBuild(story, canvasmaker=NumberedCanvas)

    size_kb = os.path.getsize(out_path) / 1024
    print(f'OK Generated: {out_path}')
    print(f'   Size: {size_kb:,.1f} KB')


if __name__ == '__main__':
    build()
