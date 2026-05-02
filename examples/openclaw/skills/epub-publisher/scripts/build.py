#!/usr/bin/env python3
"""
epub-publisher — compile a directory of markdown chapters into an EPUB 3 file.

Stdlib-only. Uses zipfile + a tiny markdown→XHTML converter. No pandoc, no
ebooklib, no Calibre. Output is a valid EPUB 3 file readable by Apple Books,
Google Play Books, Kobo, and convertible by KDP.

Usage:
    python3 build.py --title "..." --author "..." \\
        --chapters-dir /path/to/chapters --out /path/book.epub

The chapters-dir is read in lexical filename order; .md files become one
chapter each. .xhtml files in the same dir are passed through verbatim
(useful when you want pandoc's richer markdown).
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [epub-publisher] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("epub-publisher")


# --- Tiny markdown → XHTML converter -------------------------------------------
# Intentionally small. For richer markdown, the user can convert with pandoc
# externally and drop .xhtml files in chapters-dir; build.py reads both.

_RE_CODE_FENCE = re.compile(r"^```(\w*)\s*$")
_RE_HEADER     = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_RE_HR         = re.compile(r"^---+\s*$")
_RE_OL_ITEM    = re.compile(r"^\d+\.\s+(.*?)\s*$")
_RE_UL_ITEM    = re.compile(r"^[*-]\s+(.*?)\s*$")
_RE_BQ         = re.compile(r"^>\s?(.*?)\s*$")
_RE_BOLD       = re.compile(r"\*\*([^*]+)\*\*")
_RE_ITALIC     = re.compile(r"\*([^*]+)\*")
_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_LINK       = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    """Apply inline markdown rules to one line of text. Escapes HTML first."""
    s = html.escape(text)
    # Inline code first (so we don't process bold/italic inside code spans)
    s = _RE_INLINE_CODE.sub(r"<code>\1</code>", s)
    s = _RE_BOLD.sub(r"<strong>\1</strong>", s)
    s = _RE_ITALIC.sub(r"<em>\1</em>", s)
    s = _RE_LINK.sub(r'<a href="\2">\1</a>', s)
    return s


def md_to_xhtml(md: str) -> tuple[str, str]:
    """Return (chapter_title, xhtml_body). Title is taken from the first H1
    if present, else first non-empty line, else 'Chapter'."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    title: str | None = None

    in_code = False
    code_lang = ""
    in_ul = False
    in_ol = False
    in_bq = False
    para: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + " ".join(_inline(p) for p in para) + "</p>")
            para.clear()

    def close_lists_and_bq() -> None:
        nonlocal in_ul, in_ol, in_bq
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        if in_bq:
            out.append("</blockquote>")
            in_bq = False

    for line in lines:
        # Code fences toggle regardless of context
        m = _RE_CODE_FENCE.match(line)
        if m:
            flush_para()
            close_lists_and_bq()
            if not in_code:
                in_code = True
                code_lang = m.group(1)
                out.append(f'<pre><code class="lang-{html.escape(code_lang)}">'
                           if code_lang else "<pre><code>")
            else:
                in_code = False
                out.append("</code></pre>")
            continue
        if in_code:
            out.append(html.escape(line))
            continue

        if not line.strip():
            flush_para()
            close_lists_and_bq()
            continue

        m = _RE_HEADER.match(line)
        if m:
            flush_para()
            close_lists_and_bq()
            level = len(m.group(1))
            text = m.group(2).strip()
            if title is None and level == 1:
                title = text
            out.append(f"<h{level}>{_inline(text)}</h{level}>")
            continue

        if _RE_HR.match(line):
            flush_para()
            close_lists_and_bq()
            out.append("<hr/>")
            continue

        m = _RE_BQ.match(line)
        if m:
            flush_para()
            if in_ul or in_ol:
                close_lists_and_bq()
            if not in_bq:
                out.append("<blockquote>")
                in_bq = True
            out.append(f"<p>{_inline(m.group(1))}</p>")
            continue

        m = _RE_OL_ITEM.match(line)
        if m:
            flush_para()
            if in_ul or in_bq:
                close_lists_and_bq()
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        m = _RE_UL_ITEM.match(line)
        if m:
            flush_para()
            if in_ol or in_bq:
                close_lists_and_bq()
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Otherwise, accumulate paragraph
        if in_ul or in_ol or in_bq:
            close_lists_and_bq()
        para.append(line.strip())

    flush_para()
    close_lists_and_bq()
    if in_code:
        out.append("</code></pre>")  # tolerate unclosed fence

    body = "\n".join(out)
    return (title or "Chapter", body)


# --- EPUB assembly -------------------------------------------------------------

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

CSS = """body { font-family: Georgia, serif; line-height: 1.55; padding: 0 1em; }
h1, h2, h3 { font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
pre { background: #f4f4f4; padding: 0.6em; overflow-x: auto; }
code { font-family: Menlo, Consolas, monospace; }
blockquote { border-left: 3px solid #888; margin-left: 0; padding-left: 0.8em; color: #555; }
hr { border: none; border-top: 1px solid #ccc; margin: 1.5em 0; }
"""

CHAPTER_XHTML_TPL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="styles.css"/>
</head>
<body>
{body}
</body>
</html>
"""

NAV_XHTML_TPL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="styles.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""

OPF_TPL = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{lang}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{identifier}</dc:identifier>
    <dc:title>{title}</dc:title>
    {authors_meta}
    <dc:language>{lang}</dc:language>
    <dc:date>{date}</dc:date>
    {desc_meta}
    <meta property="dcterms:modified">{date}</meta>
{cover_meta}
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="styles.css" media-type="text/css"/>
{cover_manifest}
{chapter_manifest}
  </manifest>
  <spine toc="ncx">
{spine}
  </spine>
</package>
"""

NCX_TPL = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{lang}">
  <head>
    <meta name="dtb:uid" content="{identifier}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
{navpoints}
  </navMap>
</ncx>
"""


def _render_authors(authors: list[str]) -> str:
    return "\n    ".join(f"<dc:creator>{html.escape(a)}</dc:creator>"
                         for a in authors)


def _render_navpoints(chapters: list[tuple[str, str]]) -> str:
    parts = []
    for i, (title, fname) in enumerate(chapters, start=1):
        parts.append(
            f'    <navPoint id="np-{i}" playOrder="{i}">'
            f'<navLabel><text>{html.escape(title)}</text></navLabel>'
            f'<content src="{fname}"/></navPoint>'
        )
    return "\n".join(parts)


def _render_nav_items(chapters: list[tuple[str, str]]) -> str:
    return "\n".join(f'      <li><a href="{fname}">{html.escape(title)}</a></li>'
                     for title, fname in chapters)


def _render_chapter_manifest(chapters: list[tuple[str, str]]) -> str:
    parts = []
    for i, (_, fname) in enumerate(chapters, start=1):
        parts.append(f'    <item id="ch-{i}" href="{fname}" '
                     f'media-type="application/xhtml+xml"/>')
    return "\n".join(parts)


def _render_spine(chapters: list[tuple[str, str]]) -> str:
    parts = []
    for i in range(1, len(chapters) + 1):
        parts.append(f'    <itemref idref="ch-{i}"/>')
    return "\n".join(parts)


# --- Build ---------------------------------------------------------------------

def collect_chapters(chapters_dir: Path) -> list[tuple[str, str, str]]:
    """Return list of (title, xhtml_filename, xhtml_body) in lexical order."""
    if not chapters_dir.is_dir():
        log.error("chapters-dir does not exist or is not a directory: %s",
                  chapters_dir)
        sys.exit(1)
    candidates = sorted(
        list(chapters_dir.glob("*.md")) + list(chapters_dir.glob("*.xhtml"))
    )
    if not candidates:
        log.error("no .md or .xhtml files in %s", chapters_dir)
        sys.exit(1)
    out: list[tuple[str, str, str]] = []
    for i, src in enumerate(candidates, start=1):
        if src.suffix.lower() == ".md":
            title, body = md_to_xhtml(src.read_text(encoding="utf-8"))
        else:
            # Pass-through XHTML; try to extract <title>
            content = src.read_text(encoding="utf-8")
            tm = re.search(r"<title>(.*?)</title>", content, re.DOTALL | re.IGNORECASE)
            title = (tm.group(1).strip() if tm else src.stem) or "Chapter"
            body = re.sub(r"^.*?<body[^>]*>", "", content,
                          count=1, flags=re.DOTALL | re.IGNORECASE)
            body = re.sub(r"</body>.*$", "", body,
                          count=1, flags=re.DOTALL | re.IGNORECASE)
        if not title.strip():
            title = src.stem
        fname = f"chapter-{i:03d}.xhtml"
        out.append((title, fname, body))
    return out


def build_epub(args: argparse.Namespace) -> Path:
    out = Path(args.out).expanduser()
    chapters_dir = Path(args.chapters_dir).expanduser()
    cover = Path(args.cover).expanduser() if args.cover else None
    if cover is not None and not cover.exists():
        log.error("--cover does not exist: %s", cover)
        sys.exit(1)

    identifier = args.isbn or f"urn:uuid:{uuid.uuid4()}"
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chapters = collect_chapters(chapters_dir)
    log.info("collected %d chapter(s); first=%s, last=%s",
             len(chapters), chapters[0][0], chapters[-1][0])

    # Render OPF + NCX + nav
    spine = _render_spine([(t, f) for t, f, _ in chapters])
    chapter_manifest = _render_chapter_manifest([(t, f) for t, f, _ in chapters])
    authors_meta = _render_authors(args.author)
    desc_meta = (f"<dc:description>{html.escape(args.description)}</dc:description>"
                 if args.description else "")
    cover_manifest = ""
    cover_meta = ""
    if cover is not None:
        ext = cover.suffix.lstrip(".").lower() or "jpg"
        media_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        cover_manifest = (f'    <item id="cover-image" href="cover.{ext}" '
                          f'media-type="{media_type}" properties="cover-image"/>')
        cover_meta = '    <meta name="cover" content="cover-image"/>'

    opf = OPF_TPL.format(
        lang=args.language,
        identifier=html.escape(identifier),
        title=html.escape(args.title),
        authors_meta=authors_meta,
        date=date,
        desc_meta=desc_meta,
        cover_meta=cover_meta,
        cover_manifest=cover_manifest,
        chapter_manifest=chapter_manifest,
        spine=spine,
    )

    ncx = NCX_TPL.format(
        lang=args.language,
        identifier=html.escape(identifier),
        title=html.escape(args.title),
        navpoints=_render_navpoints([(t, f) for t, f, _ in chapters]),
    )

    nav = NAV_XHTML_TPL.format(
        lang=args.language,
        title=html.escape(args.title),
        items=_render_nav_items([(t, f) for t, f, _ in chapters]),
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    log.info("writing → %s", out)
    with zipfile.ZipFile(out, "w") as zf:
        # mimetype must be FIRST and stored uncompressed
        zi = zipfile.ZipInfo("mimetype")
        zi.compress_type = zipfile.ZIP_STORED
        zf.writestr(zi, "application/epub+zip")

        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/toc.ncx", ncx)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/styles.css", CSS)

        for title, fname, body in chapters:
            xhtml = CHAPTER_XHTML_TPL.format(
                lang=args.language,
                title=html.escape(title),
                body=body,
            )
            zf.writestr(f"OEBPS/{fname}", xhtml)

        if cover is not None:
            ext = cover.suffix.lstrip(".").lower() or "jpg"
            zf.writestr(f"OEBPS/cover.{ext}", cover.read_bytes())

    return out


# --- Validation ----------------------------------------------------------------

REQUIRED_ENTRIES = {
    "mimetype",
    "META-INF/container.xml",
    "OEBPS/content.opf",
    "OEBPS/toc.ncx",
    "OEBPS/nav.xhtml",
}


def validate(epub_path: Path) -> bool:
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            names = set(zf.namelist())
            missing = REQUIRED_ENTRIES - names
            if missing:
                log.error("validate: missing required entries: %s", sorted(missing))
                return False
            mt = zf.read("mimetype").decode("ascii", "replace").strip()
            if mt != "application/epub+zip":
                log.error("validate: mimetype is %r, expected 'application/epub+zip'", mt)
                return False
        return True
    except zipfile.BadZipFile as e:
        log.error("validate: bad zip: %s", e)
        return False


# --- Self-test -----------------------------------------------------------------

def self_test() -> int:
    """Build a tiny EPUB end-to-end into a temp dir and validate it."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="epub-test-") as tmp:
        td = Path(tmp)
        ch = td / "chapters"
        ch.mkdir()
        (ch / "01-one.md").write_text("# Chapter One\n\nHello, **world**.\n",
                                       encoding="utf-8")
        (ch / "02-two.md").write_text("# Chapter Two\n\nA list:\n- a\n- b\n- c\n",
                                       encoding="utf-8")
        out = td / "test.epub"
        ns = argparse.Namespace(
            title="Test", author=["Tester"],
            chapters_dir=str(ch), out=str(out), cover=None,
            language="en", description=None, isbn=None,
        )
        build_epub(ns)
        ok = validate(out)
        if not ok:
            log.error("self-test: validation FAILED")
            return 1
        size = out.stat().st_size
        log.info("self-test OK; %s (%d bytes)", out.name, size)
        if size < 500:
            log.error("self-test: file unusually small")
            return 1
        return 0


# --- Main ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="epub-publisher")
    parser.add_argument("--title")
    parser.add_argument("--author", action="append", default=[],
                        help="Repeat for multiple authors")
    parser.add_argument("--chapters-dir")
    parser.add_argument("--out")
    parser.add_argument("--cover", default=None)
    parser.add_argument("--language", default="en")
    parser.add_argument("--description", default=None)
    parser.add_argument("--isbn", default=None)
    parser.add_argument("--self-test", action="store_true",
                        help="Build a tiny test EPUB and validate it")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if not args.title or not args.author or not args.chapters_dir or not args.out:
        parser.error("--title, --author, --chapters-dir, --out are required "
                     "(unless --self-test)")

    out = build_epub(args)
    if not validate(out):
        return 1
    log.info("✓ EPUB ready: %s (%d bytes)", out, out.stat().st_size)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
