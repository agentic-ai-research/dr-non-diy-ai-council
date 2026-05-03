#!/usr/bin/env python3
"""
quarkdown — compile Markdown into slides / paged PDFs / wikis / HTML
via the Quarkdown CLI.

Sister to epub-publisher. Stdlib-only Python wrapper around `quarkdown c`.
On first run the script auto-installs Quarkdown via Homebrew and resolves
keg-only Java (openjdk@21) from its Homebrew prefix so no manual PATH
tweaking is needed. The user just runs the script; prereqs arrive automatically.

Usage:
    python3 build.py --source talk.md --type slides --pdf --out /tmp/talk
    python3 build.py --self-test
"""

from __future__ import annotations

import argparse
import logging
import os
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

# Homebrew keg paths for Java (openjdk@21 installed via `brew install openjdk@21`)
_JAVA_KEG_CANDIDATES = [
    Path("/opt/homebrew/opt/openjdk@21/bin/java"),   # Apple Silicon
    Path("/usr/local/opt/openjdk@21/bin/java"),       # Intel Mac
    Path("/opt/homebrew/opt/openjdk/bin/java"),        # latest openjdk keg
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [quarkdown] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("quarkdown")


# --- Preflight -----------------------------------------------------------------

def _which(bin_name: str) -> str | None:
    """Return full path of bin_name if found on PATH, else None."""
    return shutil.which(bin_name)


def _find_java() -> str | None:
    """Return a usable `java` binary path (PATH first, then Homebrew keg)."""
    on_path = _which("java")
    if on_path:
        return on_path
    for candidate in _JAVA_KEG_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def _brew_install(pkg: str) -> bool:
    """Run `brew install <pkg>` and return True on success."""
    brew = _which("brew")
    if not brew:
        return False
    log.info("auto-installing %s via Homebrew…", pkg)
    result = subprocess.run([brew, "install", pkg], capture_output=False)
    return result.returncode == 0


def preflight() -> str:
    """Ensure quarkdown and java are available; auto-install quarkdown if missing.

    Returns the resolved path to the `java` binary (used to inject JAVA_HOME
    into the quarkdown subprocess when java is keg-only).
    """
    # --- Java ---
    java_path = _find_java()
    if not java_path:
        log.error(
            "Java 17+ not found on PATH or in Homebrew keg paths. "
            "Fix: brew install openjdk@21"
        )
        sys.exit(1)
    log.info("java: %s", java_path)

    # --- Quarkdown ---
    qd_path = _which("quarkdown")
    if not qd_path:
        log.warning("quarkdown not on PATH — attempting auto-install via Homebrew")
        ok = _brew_install("quarkdown-labs/quarkdown/quarkdown")
        if not ok:
            log.error(
                "Auto-install failed. Run manually:\n"
                "    brew install quarkdown-labs/quarkdown/quarkdown"
            )
            sys.exit(1)
        qd_path = _which("quarkdown")
        if not qd_path:
            log.error("quarkdown still not found after install — restart your shell?")
            sys.exit(1)
    log.info("quarkdown: %s", qd_path)

    return java_path


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
                  extra_args: list[str], java_path: str | None = None) -> None:
    """Invoke `quarkdown c` with the assembled args.

    When `java_path` points to a Homebrew keg binary (not on the system PATH),
    we inject JAVA_HOME so that the Quarkdown JVM launcher can find the runtime.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = ["quarkdown", "c", str(source), "--out", str(out)]
    if pdf:
        cmd.append("--pdf")
    if clean:
        cmd.append("--clean")
    cmd.extend(extra_args)
    log.info("running: %s", " ".join(cmd))

    env = os.environ.copy()
    if java_path and not shutil.which("java"):
        # keg-only Java: set JAVA_HOME so the quarkdown launcher finds it
        java_home = str(Path(java_path).parent.parent)  # bin/java -> parent dir
        env["JAVA_HOME"] = java_home
        env["PATH"] = str(Path(java_path).parent) + os.pathsep + env.get("PATH", "")
        log.info("keg-only Java detected — JAVA_HOME=%s", java_home)

    try:
        subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as e:
        log.error("quarkdown exited with code %d", e.returncode)
        sys.exit(e.returncode)


# --- Self-test -----------------------------------------------------------------

def self_test() -> int:
    """Write a tiny .qd, compile to plain HTML, assert index.html exists."""
    java_path = preflight()
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
    run_quarkdown(src, out, pdf=False, clean=True, extra_args=[], java_path=java_path)
    # Quarkdown writes to <out>/<docname>/index.html, not <out>/index.html
    found = next(out.rglob("index.html"), None)
    if not found:
        log.error("self-test failed: no index.html found under %s", out)
        return 1
    size = found.stat().st_size
    log.info("✓ self-test passed: %s (%d bytes)", found, size)
    print(found)
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

    java_path = preflight()

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
    run_quarkdown(prepared, out_dir, pdf=pdf, clean=clean, extra_args=extra,
                  java_path=java_path)

    # Quarkdown output location depends on mode:
    #   --pdf only  → <out_dir>/<stem>.pdf  (HTML is a temp artefact, cleaned up)
    #   HTML only   → <out_dir>/<docname>/index.html
    output = next(out_dir.rglob("*.pdf"), None) or next(out_dir.rglob("index.html"), None)
    if output:
        log.info("✓ wrote %s", output)
        print(output)
    else:
        log.warning("compile finished but no output found under %s", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
