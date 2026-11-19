"""Documents: a .docx writer and reader (standard library only), a small PDF writer, and the reports folder.

Blocks are a list of (kind, text) pairs: ("title", ..) ("h1", ..) ("p", ..) ("bullet", ..).
Urdu / Arabic paragraphs are written right-to-left automatically.
Nothing here needs a third-party package, so it also works in the frozen .exe.
"""
from __future__ import annotations

import io
import logging
import os
import re
import time
import zipfile
from xml.sax.saxutils import escape

from . import config

log = logging.getLogger("jarvis.docs")

EXTS = (".docx", ".pdf", ".txt", ".md")
_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# ---------------------------------------------------------------------------- folder helpers
def reports_dir() -> str:
    d = config.REPORTS_DIR
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        log.exception("cannot create reports folder")
    return d


def safe_name(title: str, limit: int = 48) -> str:
    s = re.sub(r"[^\w\- ]+", " ", title or "", flags=re.U)
    s = re.sub(r"\s+", " ", s).strip().replace(" ", "-")
    return (s[:limit].strip("-") or "report")


def unique_path(title: str, ext: str, prefix: str = "") -> str:
    """reports/<prefix>-<title>-<date>.ext  (a counter is added if the file already exists)."""
    base = "-".join(x for x in (prefix, safe_name(title), time.strftime("%Y-%m-%d")) if x)
    path = os.path.join(reports_dir(), base + ext)
    n = 2
    while os.path.exists(path):
        path = os.path.join(reports_dir(), "%s-%d%s" % (base, n, ext))
        n += 1
    return path


def list_reports() -> list[tuple[str, float]]:
    """[(file name, mtime)] newest first."""
    out = []
    try:
        for f in os.listdir(reports_dir()):
            if f.lower().endswith(EXTS):
                out.append((f, os.path.getmtime(os.path.join(reports_dir(), f))))
    except OSError:
        return []
    return sorted(out, key=lambda x: x[1], reverse=True)


def find_report(keyword: str = "") -> str | None:
    """Newest report whose name contains every word of keyword (no keyword = the newest one)."""
    files = [f for f, _ in list_reports()]
    words = [w for w in re.findall(r"\w+", (keyword or "").lower()) if w not in ("the", "a", "report", "file", "document")]
    if not words:
        return files[0] if files else None
    for f in files:
        if all(w in f.lower() for w in words):
            return f
    return None


def read_report(name: str) -> str | None:
    """Text of a report. PDF files are listed but not read (returns None)."""
    path = name if os.path.isabs(name) else os.path.join(reports_dir(), name)
    low = path.lower()
    try:
        if low.endswith(".docx"):
            return read_docx(path)
        if low.endswith((".txt", ".md")):
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    except Exception:
        log.exception("cannot read %s", path)
    return None


# ---------------------------------------------------------------------------- docx
_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
       '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
         '</Relationships>')
_DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
             '</Relationships>')
_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Arial"/>'
           '<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>'
           '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
           '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
           '<w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3A93"/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr></w:style>'
           '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
           '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/></w:pPr><w:rPr><w:b/><w:color w:val="2E5CB8"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>'
           '</w:styles>')


def _clean(s: str) -> str:
    return _BAD_XML.sub("", str(s))


def _para(kind: str, text: str) -> str:
    text = _clean(text)
    rtl = bool(_ARABIC.search(text))
    style = {"title": "Title", "h1": "Heading1"}.get(kind, "")
    if kind == "bullet":
        text = "\u2022  " + text
    ppr = ("<w:pStyle w:val=\"%s\"/>" % style if style else "") + ("<w:bidi/><w:jc w:val=\"left\"/>" if rtl else "")
    rpr = "<w:rtl/>" if rtl else ""
    runs = []
    for i, line in enumerate(text.split("\n")):
        br = "<w:br/>" if i else ""
        runs.append("<w:r>%s%s<w:t xml:space=\"preserve\">%s</w:t></w:r>" % ("<w:rPr>%s</w:rPr>" % rpr if rpr else "", br, escape(line)))
    return "<w:p>%s%s</w:p>" % ("<w:pPr>%s</w:pPr>" % ppr if ppr else "", "".join(runs))


def blocks_from_text(text: str, title: str = "") -> list:
    """Plain text (blank-line separated paragraphs, '-' / '*' bullets, 'LINES:' headings) -> blocks."""
    blocks = [("title", title)] if title else []
    for raw in re.split(r"\n\s*\n", (text or "").strip()):
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split("\n")
        if len(lines) == 1 and re.match(r"^#{1,3}\s+\S", lines[0]):
            blocks.append(("h1", re.sub(r"^#{1,3}\s+", "", lines[0])))
            continue
        para = []
        for ln in lines:
            m = re.match(r"^\s*(?:[-*\u2022]|\d+[.)])\s+(.*)$", ln)
            if m:
                if para:
                    blocks.append(("p", " ".join(para)))
                    para = []
                blocks.append(("bullet", m.group(1)))
            elif re.match(r"^#{1,3}\s+\S", ln):
                if para:
                    blocks.append(("p", " ".join(para)))
                    para = []
                blocks.append(("h1", re.sub(r"^#{1,3}\s+", "", ln)))
            else:
                para.append(ln.strip())
        if para:
            blocks.append(("p", " ".join(para)))
    return blocks


def write_docx(path: str, title: str, blocks) -> str:
    """Write a Word file. `blocks` may be a list of (kind, text) or a plain string."""
    if isinstance(blocks, str):
        blocks = blocks_from_text(blocks)
    body = []
    if title:
        body.append(_para("title", title))
    stamp = time.strftime("%d %B %Y, %I:%M %p")
    body.append(_para("p", "Created by J.A.R.V.I.S  \u00b7  " + stamp))
    body += [_para(k, t) for k, t in blocks if str(t).strip()]
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>%s'
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
           '</w:body></w:document>') % "".join(body)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
    os.replace(tmp, path)
    return path


def read_docx(path: str) -> str:
    """All paragraph text of a .docx (works on files written by Word too). Paragraphs are separated by blank lines."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, flags=re.S):
        p = re.sub(r"<w:tab\s*/>", "\t", p)
        p = re.sub(r"<w:br\s*/>", "\n", p)
        txt = "".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", p, flags=re.S))
        txt = (txt.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))
        out.append(txt)
    return "\n\n".join(x for x in out if x.strip())


def append_note_docx(path: str, text: str) -> str:
    """Add one timestamped line to a daily notes .docx (created on first use)."""
    items = []
    if os.path.isfile(path):
        try:
            old = read_docx(path).split("\n\n")
            items = [re.sub(r"^\u2022\s+", "", x) for x in old[2:] if x.strip()]                   # drop the title and the "Created by" line
        except Exception:
            items = []
    items.append("%s  %s" % (time.strftime("%I:%M %p"), text.strip()))
    return write_docx(path, "Notes - " + time.strftime("%d %B %Y"), [("bullet", x) for x in items])


# ---------------------------------------------------------------------------- pdf (Latin text only)
def pdf_possible(text: str) -> bool:
    return not _ARABIC.search(text or "")


def _pdf_escape(s: str) -> str:
    s = s.encode("cp1252", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: str, title: str, blocks) -> str:
    """A small, dependable A4 PDF (Helvetica, wrapped text, several pages). Latin text only: Urdu goes to Word."""
    if isinstance(blocks, str):
        blocks = blocks_from_text(blocks)
    width, height, margin = 595, 842, 56
    items = [("title", title)] if title else []
    items += list(blocks)
    pages, cur, y = [], [], height - margin

    def newpage():
        nonlocal cur, y
        if cur:
            pages.append(cur)
        cur, y = [], height - margin

    for kind, text in items:
        size, lead, bold = {"title": (20, 28, True), "h1": (14, 22, True)}.get(kind, (11, 15, False))
        text = ("\u2022 " + text) if kind == "bullet" else text
        per = max(20, int((width - 2 * margin) / (size * (0.55 if bold else 0.5))))
        lines = []
        for para in str(text).split("\n"):
            w = para.split(" ")
            line = ""
            for word in w:
                if line and len(line) + 1 + len(word) > per:
                    lines.append(line)
                    line = word
                else:
                    line = (line + " " + word).strip()
            lines.append(line)
        if kind == "h1":
            y -= 6
        for ln in lines:
            if y < margin + lead:
                newpage()
            cur.append((margin, y, size, bold, ln))
            y -= lead
        y -= 5
    if cur or not pages:
        pages.append(cur)
    objs: list[bytes] = []

    def add(b: str | bytes) -> int:
        objs.append(b if isinstance(b, bytes) else b.encode("latin-1"))
        return len(objs)

    add("<< /Type /Catalog /Pages 2 0 R >>")
    add("")                                                    # pages (filled in below)
    f1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for pg in pages:
        ops = ["BT"]
        for x, yy, size, bold, ln in pg:
            ops.append("/F%d %d Tf 1 0 0 1 %d %d Tm (%s) Tj" % (2 if bold else 1, size, x, yy, _pdf_escape(ln)))
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        pid = add("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
                  % (width, height, f1, f2, cid))
        kids.append(pid)
    objs[1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids))).encode("latin-1")
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(buf.tell())
        buf.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = buf.tell()
    buf.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offs:
        buf.write(b"%010d 00000 n \n" % o)
    buf.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(buf.getvalue())
    os.replace(tmp, path)
    return path
