#!/usr/bin/env python3
"""
quarkdown — compile Markdown into slides / paged PDFs / wikis / HTML
via the Quarkdown CLI.

Sister to epub-publisher. Stdlib-only Python wrapper around `quarkdown c`.
The user runs `brew install quarkdown-labs/quarkdown/quarkdown` once; this
script does the frontmatter injection, doctype auto-detection, and output
plumbing so the same skill handles slides, paged books, wikis, and plain HTML.

Usage:
    python3 build.py --source talk.md --type slides --pdf --out /tmp/talk
    python3 build.py --self-test
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --- Constants -----------------------------------------------------------------

VALID_DOCTYPES = ("plain", "paged", "slides", "docs")

DOCTYPE_KEYWORDS = {
    "slides": ("slides", "deck", "talk", "presentation"),
    "paged":  ("book", "chapter", "manuscript", "paper"),
    "docs":   ("wiki", "docs", "kb", "knowledge-base", "knowledge_base"),
    # plain is the fallback
}

DEFAULT_OUT_BASE = Path.home() / ".openclaw" / "workspace" / "quarkdown"

INSTALL_HINT = """\
Quarkdown or Java is missing. One-time install on macOS:

    brew install --cask temurin@21                    # Java 17+
    brew install quarkdown-labs/quarkdown/quarkdown   # Quarkdown CLI

Verify:
    java -version    # >= 17
    quarkdown --version
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [quarkdown] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("quarkdown")


# --- Preflight -----------------------------------------------------------------

def _which(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def preflight() -> None:
    """Verify quarkdown + java are on PATH; print install hint and exit if not."""
    missing = [b for b in ("quarkdown", "java") if not _which(b)]
    if missing:
        log.error("missing on PATH: %s", ", ".join(missing))
        print(INSTALL_HINT, file=sys.stderr)
        sys.exit(1)


# --- Doctype detection ---------------------------------------------------------

def detect_doctype(source: Path) -> str:
    """Pick a doctype from the source filename or its parent dir; default 'plain'.

    Checks the file stem first, then the parent directory name. This catches
    both `bangkok-talk.md` (slides) and `knowledge-base/index.md` (docs).
    """
    stem = source.stem.lower()
    parent = source.parent.name.lower() if source.parent.name else ""
    haystack = f"{stem} {parent}"
    for doctype, keywords in DOCTYPE_KEYWORDS.items():
        if any(k in haystack for k in keywords):
            return doctype
    return "plain"


# --- Frontmatter ---------------------------------------------------------------

def build_frontmatter(*, title: str, doctype: str, language: str,
                      author: str) -> str:
    """Render the `.docname / .doctype / .doclang / .docauthors` header."""
    lines = [
        f".docname {{{title}}}",
        f".doctype {{{doctype}}}",
        f".doclang {{{language}}}",
    ]
    if author.strip():
        lines.append(".docauthors")
        lines.append(f"    - {author.strip()}")
    return "\n".join(lines) + "\n\n"


def prepare_source(source: Path, *, title: str, doctype: str, language: str,
                   author: str) -> Path:
    """Return a path to a .qd file ready to compile.

    - If `source` is already `.qd`, return it unchanged.
    - If `source` is `.md`, write a temp `.qd` with frontmatter prepended.
    """
    if source.suffix.lower() == ".qd":
        return source
    body = source.read_text(encoding="utf-8")
    front = build_frontmatter(
        title=title, doctype=doctype, language=language, author=author
    )
    tmp = Path(tempfile.mkdtemp(prefix="quarkdown-")) / (source.stem + ".qd")
    tmp.write_text(front + body, encoding="utf-8")
    log.info("frontmatter injected → %s (doctype=%s, lang=%s)", tmp, doctype, language)
    return tmp


# --- Compile -------------------------------------------------------------------

def run_quarkdown(source: Path, out: Path, *, pdf: bool, clean: bool,
                  extra_args: list[str]) -> None:
    """Invoke `quarkdown c` with the assembled args."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = ["quarkdown", "c", str(source), "--out", str(out)]
    if pdf:
        cmd.append("--pdf")
    if clean:
        cmd.append("--clean")
    cmd.extend(extra_args)
    log.info("running: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        log.error("quarkdown exited with code %d", e.returncode)
        sys.exit(e.returncode)


# --- Self-test -----------------------------------------------------------------

def self_test() -> int:
    """Write a tiny .qd, compile to plain HTML, assert index.html exists."""
    preflight()
    work = Path(tempfile.mkdtemp(prefix="quarkdown-selftest-"))
    src = work / "hello.qd"
    src.write_text(
        ".docname {Self Test}\n"
        ".doctype {plain}\n"
        ".doclang {en}\n"
        "\n"
        "# Hello, Quarkdown\n"
        "\n"
        "This is the self-test. If you can read this, the wrapper is wired correctly.\n",
        encoding="utf-8",
    )
    out = work / "out"
    run_quarkdown(src, out, pdf=False, clean=True, extra_args=[])
    expected = out / "index.html"
    if not expected.exists():
        log.error("self-test failed: %s missing", expected)
        return 1
    size = expected.stat().st_size
    log.info("✓ self-test passed: %s (%d bytes)", expected, size)
    print(expected)
    return 0


# --- Main ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="quarkdown")
    parser.add_argument("--source", help="Path to a .md or .qd file")
    parser.add_argument(
        "--type", choices=VALID_DOCTYPES, default=None,
        help="Doctype: plain / paged / slides / docs (default: auto-detect from filename)",
    )
    parser.add_argument("--out", default=None,
                        help="Output directory (default: ~/.openclaw/workspace/quarkdown/<basename>/)")
    parser.add_argument("--pdf", action="store_true",
                        help="Also export PDF (default: auto-on for paged+slides)")
    parser.add_argument("--no-pdf", action="store_true",
                        help="Force-disable PDF even for paged+slides")
    parser.add_argument("--title", default=None, help="Document title")
    parser.add_argument("--author", default="", help="Author name (omit for none)")
    parser.add_argument("--language", default="en", help="BCP-47 language code")
    parser.add_argument("--clean", action="store_true", default=True,
                        help="Wipe output directory first (default: on)")
    parser.add_argument("--no-clean", action="store_true",
                        help="Keep existing output directory contents")
    parser.add_argument("--extra-args", default="",
                        help='Pass-through to `quarkdown c`, e.g. "--strict --pretty"')
    parser.add_argument("--self-test", action="store_true",
                        help="Run the self-test and exit")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if not args.source:
        parser.error("--source is required (or use --self-test)")
    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        log.error("source does not exist: %s", source)
        return 1
    if source.suffix.lower() not in (".md", ".qd"):
        log.error("source must be .md or .qd (got %s)", source.suffix)
        return 1

    preflight()

    doctype = args.type or detect_doctype(source)
    if doctype not in VALID_DOCTYPES:
        log.error("invalid doctype: %s", doctype)
        return 1

    title = args.title or source.stem.replace("-", " ").replace("_", " ")
    out_dir = Path(args.out).expanduser() if args.out else (DEFAULT_OUT_BASE / source.stem)
    out_dir = out_dir.resolve()

    # PDF default: on for paged+slides, off for plain+docs — overridable
    if args.no_pdf:
        pdf = False
    elif args.pdf:
        pdf = True
    else:
        pdf = doctype in ("paged", "slides")

    clean = (not args.no_clean) and args.clean
    extra = args.extra_args.split() if args.extra_args else []

    log.info("source=%s · type=%s · pdf=%s · out=%s", source, doctype, pdf, out_dir)
    prepared = prepare_source(
        source,
        title=title, doctype=doctype, language=args.language, author=args.author,
    )
    run_quarkdown(prepared, out_dir, pdf=pdf, clean=clean, extra_args=extra)

    index = out_dir / "index.html"
    if index.exists():
        log.info("✓ wrote %s", index)
        print(index)
    else:
        log.warning("compile finished but %s not found — check %s", index, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
