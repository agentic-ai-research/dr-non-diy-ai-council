---
name: quarkdown
description: "Compile Markdown into slides, paged PDFs, wikis, or HTML using Quarkdown — a Turing-complete typesetting layer over Markdown. Single .qd source → reveal.js slides, paged.js books, sidebar-style docs, or plain HTML, all to PDF on demand. Triggers: make slides from this, compile to PDF, turn this into a presentation, paged book from chapters, publish as a wiki."
metadata:
  openclaw:
    requires:
      bins: [quarkdown, java, node, npm]
      env: []
  emoji: "🪐"
---

# Quarkdown

Compile a Markdown (`.md`) or Quarkdown (`.qd`) file into a slide deck, a paged PDF book, a wiki-style site, or plain HTML — using [Quarkdown](https://github.com/iamgio/quarkdown), a Turing-complete typesetting system that extends CommonMark with functions, variables, and loops.

## When to use

Triggers — *"make me slides from this Markdown," "compile to PDF," "turn these chapters into a paged book," "publish this as a wiki," "generate a reveal.js deck from /Brain/Talks/2026-talk.md."*

For EPUB (Apple Books / KDP) use `epub-publisher`. For raw HTML with no scripting layer, just open the `.md` in any reader. Use `quarkdown` when you want **slides**, **paged books**, **PDF**, or **wiki sites** from a single source.

## Prerequisites (one-time)

```bash
# Java 17+ (Quarkdown is JVM-based)
brew install --cask temurin@21

# Quarkdown itself
brew install quarkdown-labs/quarkdown/quarkdown

# Node + npm are already on most dev Macs; verify:
node --version && npm --version
```

The skill runs `which quarkdown && which java` on every invocation and prints the install commands above if anything is missing.

## Usage

```bash
# Slides from a Markdown talk (auto-detects "slides" / "deck" in filename)
python3 ~/.openclaw/skills/quarkdown/scripts/build.py \
  --source ~/Brain/Talks/2026-05-bangkok-talk.md \
  --type slides \
  --out ~/.openclaw/workspace/quarkdown/bangkok-talk \
  --pdf \
  --title "Smart Cities ≠ Smart Citizens" \
  --author "Dr Non Arkara"

# Paged book from a folder full of chapter .md files (concatenated, then compiled)
python3 ~/.openclaw/skills/quarkdown/scripts/build.py \
  --source ~/Brain/Books/SLIC-V1/manuscript.md \
  --type paged \
  --pdf \
  --out ~/Brain/Books/SLIC-V1/dist

# Wiki / docs site
python3 ~/.openclaw/skills/quarkdown/scripts/build.py \
  --source ~/Brain/Wiki/index.md \
  --type docs \
  --out ~/Brain/Wiki/dist
```

## Args

| Flag | Default | Notes |
|---|---|---|
| `--source` | (required) | Path to a `.md` or `.qd` file. If `.md`, frontmatter is auto-prepended. |
| `--type` | auto | `plain` / `paged` / `slides` / `docs`. Auto-detect from filename keywords. |
| `--out` | `~/.openclaw/workspace/quarkdown/<basename>/` | Output directory. |
| `--pdf` | auto (true for `paged`+`slides`) | Adds `--pdf` to the quarkdown call. First run pulls Puppeteer (~100 MB, ~2 min). |
| `--title` | source filename | → `.docname{}` |
| `--author` | "" | → `.docauthors{}` (skipped if empty) |
| `--language` | `en` | → `.doclang{}` (BCP-47; `th` for Thai). |
| `--clean` | true | Wipe `--out` directory before build. |
| `--extra-args` | "" | Pass-through to `quarkdown c` (e.g. `--strict`, `--pretty`, `-l <libs>`). |
| `--self-test` | — | Write a tiny demo `.qd`, compile to plain HTML, assert `index.html` exists, exit 0. |

## Doctype auto-detection

The script picks `--type` from the source filename if not explicit:

| Filename contains... | Picks |
|---|---|
| `slides`, `deck`, `talk` | `slides` |
| `book`, `chapter`, `manuscript`, `paper` | `paged` |
| `wiki`, `docs`, `kb`, `knowledge-base` | `docs` |
| (anything else) | `plain` |

Override anytime with explicit `--type`.

## Frontmatter injection

When `--source` is a plain `.md`, the script writes a temp `.qd` that begins with:

```
.docname {<title>}
.doctype {<type>}
.doclang {<language>}
.docauthors
    - <author>
```

…then concatenates your original Markdown. Existing CommonMark/GFM is valid Quarkdown, so no rewriting needed.

If `--source` is already `.qd`, it's compiled as-is (no injection).

## Output

The compiled site/deck/book lives at `<out>/`. Open `<out>/index.html` in a browser, or grab the PDF at `<out>/<title>.pdf` (when `--pdf` is set).

## Verification

```bash
# Self-test — writes a 6-line .qd, compiles to plain HTML, asserts index.html
python3 ~/.openclaw/skills/quarkdown/scripts/build.py --self-test

# Smoke test
printf '# Hello\n\nFirst slide.\n\n---\n\n## Next\n\nSecond slide.\n' > /tmp/test.md
python3 ~/.openclaw/skills/quarkdown/scripts/build.py \
  --source /tmp/test.md --type slides --out /tmp/test-out
open /tmp/test-out/index.html
```

## Why not pandoc?

Pandoc covers similar ground but needs Haskell + LaTeX (heavy install) for clean PDF output. Quarkdown's slides+paged+docs+plain matrix from one source, plus the inline scripting layer (`{.if}`, `{.foreach}`, custom functions), makes it a sharper fit for the council's "single-source-multi-output" style. Pandoc remains the right tool for academic LaTeX papers; Quarkdown is the right tool for talks, books, and docs sites.
