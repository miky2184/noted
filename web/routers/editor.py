"""Markdown editor — export to DOCX and PDF saved in doc_root."""
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()


class ExportRequest(BaseModel):
    content: str          # markdown text
    filename: str = ""    # optional filename hint (without extension)


def _doc_root() -> Path:
    from db.config import get_doc_root
    p = Path(get_doc_root()).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(hint: str, ext: str) -> str:
    hint = hint.strip() or f"nota_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    hint = re.sub(r'[^\w\-_. ]', '', hint).strip().replace(' ', '_')
    return f"{hint}.{ext}"


# ── DOCX ──────────────────────────────────────────────────────────────────────

def _md_to_docx(content: str, out_path: Path) -> None:
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Default style tweaks
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(11)

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.startswith('```'):
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i])
                i += 1
            p = doc.add_paragraph()
            p.style = doc.styles['Normal']
            run = p.add_run('\n'.join(code_lines))
            run.font.name = 'Courier New'
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
            i += 1
            continue

        # Headings
        if line.startswith('### '):
            doc.add_heading(line[4:].strip(), level=3)
        elif line.startswith('## '):
            doc.add_heading(line[3:].strip(), level=2)
        elif line.startswith('# '):
            doc.add_heading(line[2:].strip(), level=1)

        # Horizontal rule
        elif re.match(r'^[-*_]{3,}$', line.strip()):
            p = doc.add_paragraph()
            p.paragraph_format.border_bottom = True  # cosmetic only

        # Unordered list
        elif re.match(r'^[-*+] ', line):
            text = line[2:].strip()
            p = doc.add_paragraph(style='List Bullet')
            _add_inline(p, text)

        # Ordered list
        elif re.match(r'^\d+\. ', line):
            text = re.sub(r'^\d+\. ', '', line).strip()
            p = doc.add_paragraph(style='List Number')
            _add_inline(p, text)

        # Blockquote
        elif line.startswith('> '):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(20)
            run = p.add_run(line[2:].strip())
            run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
            run.font.italic = True

        # Table
        elif '|' in line and i + 1 < len(lines) and re.match(r'^[\|\s\-:]+$', lines[i + 1]):
            headers = [c.strip() for c in line.strip('|').split('|')]
            i += 2  # skip separator
            rows = []
            while i < len(lines) and '|' in lines[i]:
                rows.append([c.strip() for c in lines[i].strip('|').split('|')])
                i += 1
            table = doc.add_table(rows=1 + len(rows), cols=len(headers))
            table.style = 'Table Grid'
            for j, h in enumerate(headers):
                cell = table.rows[0].cells[j]
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True
            for r_idx, row in enumerate(rows):
                for j, cell_text in enumerate(row):
                    if j < len(table.columns):
                        table.rows[r_idx + 1].cells[j].text = cell_text
            continue

        # Empty line
        elif line.strip() == '':
            pass  # natural paragraph break

        # Normal paragraph
        else:
            p = doc.add_paragraph()
            _add_inline(p, line)

        i += 1

    doc.save(str(out_path))


def _add_inline(paragraph, text: str) -> None:
    """Add text to paragraph handling **bold**, *italic*, `code`."""
    # Pattern: **bold**, *italic*, `code`
    pattern = re.compile(r'(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)')
    last = 0
    for m in pattern.finditer(text):
        # Plain text before
        if m.start() > last:
            paragraph.add_run(text[last:m.start()])
        full = m.group(0)
        if full.startswith('**'):
            run = paragraph.add_run(m.group(2))
            run.bold = True
        elif full.startswith('*'):
            run = paragraph.add_run(m.group(3))
            run.italic = True
        elif full.startswith('`'):
            from docx.shared import Pt, RGBColor
            run = paragraph.add_run(m.group(4))
            run.font.name = 'Courier New'
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
        last = m.end()
    if last < len(text):
        paragraph.add_run(text[last:])


# ── PDF / HTML print ──────────────────────────────────────────────────────────

_PRINT_CSS = """
body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #1a1a2e; margin: 2cm; }
h1 { font-size: 22pt; border-bottom: 2px solid #6366f1; padding-bottom: 4px; color: #312e81; }
h2 { font-size: 16pt; color: #4338ca; margin-top: 18px; }
h3 { font-size: 13pt; color: #4f46e5; margin-top: 14px; }
p { margin: 6px 0 10px; }
code { font-family: 'Courier New', monospace; font-size: 9pt; background: #f1f3f8; padding: 1px 4px; border-radius: 3px; color: #6b7280; }
pre { background: #f1f3f8; padding: 10px 14px; border-radius: 6px; font-size: 9pt; font-family: 'Courier New', monospace; color: #374151; }
ul, ol { margin: 6px 0 10px 20px; }
li { margin-bottom: 3px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 10pt; }
th { background: #6366f1; color: white; padding: 6px 10px; text-align: left; }
td { border: 1px solid #dde1ee; padding: 5px 10px; }
tr:nth-child(even) td { background: #f8f9fc; }
blockquote { border-left: 3px solid #6366f1; margin: 8px 0; padding: 4px 12px; color: #6b7280; font-style: italic; }
hr { border: none; border-top: 1px solid #dde1ee; margin: 16px 0; }
strong { color: #1a1a2e; }
@media print { body { margin: 1cm; } }
"""

def _md_to_print_html(content: str) -> str:
    import markdown as md_lib
    html_body = md_lib.markdown(content, extensions=['tables', 'fenced_code', 'nl2br'])
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_PRINT_CSS}</style></head><body>{html_body}"
        f"<script>window.onload=function(){{window.print();}}</script>"
        f"</body></html>"
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/api/editor/export/docx")
async def api_export_docx(body: ExportRequest):
    name = _safe_name(body.filename, "docx")
    out = _doc_root() / name
    try:
        _md_to_docx(body.content, out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(str(out), filename=name,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.post("/api/editor/export/pdf")
async def api_export_pdf(body: ExportRequest):
    try:
        import markdown as md_lib  # noqa
    except ImportError:
        raise HTTPException(status_code=501, detail="Installa: pip install markdown")
    try:
        from fastapi.responses import HTMLResponse
        html = _md_to_print_html(body.content)
        return HTMLResponse(content=html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/editor/export/md")
async def api_export_md(body: ExportRequest):
    from fastapi.responses import Response
    name = _safe_name(body.filename, "md")
    return Response(
        content=body.content.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/api/editor/export/txt")
async def api_export_txt(body: ExportRequest):
    from fastapi.responses import Response
    import re as _re
    # strip markdown syntax for plain text
    text = body.content
    text = _re.sub(r'#{1,6}\s*', '', text)
    text = _re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = _re.sub(r'\*(.+?)\*', r'\1', text)
    text = _re.sub(r'`(.+?)`', r'\1', text)
    text = _re.sub(r'^\s*[-*+] ', '• ', text, flags=_re.MULTILINE)
    name = _safe_name(body.filename, "txt")
    return Response(
        content=text.encode("utf-8"),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
