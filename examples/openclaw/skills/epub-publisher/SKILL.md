---
name: epub-publisher
description: "Build a valid EPUB 3 ebook from a directory of markdown chapters + optional cover image. Stdlib-only Python — no Calibre, no pandoc, no pip install. Drops a single .epub file ready for Apple Books, Google Play Books, Amazon KDP (after conversion), Kobo. Triggers: make me an ebook, publish a book, EPUB from these chapters, compile the writing into an ebook."
metadata:
  openclaw:
    requires:
      bins: [python3]
      env: []
  emoji: "📚"
---

# EPUB Publisher

Compile a directory of markdown chapters into a single, valid **EPUB 3** file. No external tools required — stdlib only (`zipfile` + a tiny markdown subset → XHTML).

## When to use

Triggers — *"compile my chapters into an ebook," "make me an EPUB," "publish this writing as a book," "I have 12 markdown files in /Drafts/Q3-Smart-Cities, turn them into a book."*

For PDFs, use `pdf-publisher`. For RSS-published podcasts, use `podcast-rss-publisher`. EPUB is the format Apple Books, Google Play Books, Kobo, and most reading apps want; KDP wants `.epub` upload then auto-converts.

## Usage

```bash
python3 ~/.openclaw/skills/epub-publisher/scripts/build.py \
  --title "Smart City Liveability Index — Volume 1" \
  --author "Dr Non Arkara" \
  --chapters-dir ~/Brain/Books/SLIC-V1/chapters \
  --cover ~/Brain/Books/SLIC-V1/cover.jpg \
  --out ~/Brain/Books/SLIC-V1/SLIC-V1.epub \
  --language en \
  --description "Free, open-data alternative to EIU and Mercer for Southeast Asian cities."
```

## Chapter directory layout

The script reads `--chapters-dir` and treats every `.md` file as one chapter, in **lexical filename order**. Use a numeric prefix to control order:

```
chapters/
├── 00-frontmatter.md         # optional preface / dedication
├── 01-introduction.md
├── 02-methodology.md
├── 03-bangkok.md
├── 04-singapore.md
├── 05-jakarta.md
├── …
├── 99-acknowledgements.md
```

Each chapter's first `# Heading` line becomes the chapter title. If a chapter has no heading, the filename (without prefix and `.md`) is used.

## Args

| Flag | Default | Notes |
|---|---|---|
| `--title` | (required) | Book title. |
| `--author` | (required) | Single author name. For multiple, repeat: `--author "X" --author "Y"`. |
| `--chapters-dir` | (required) | Directory of `.md` files. |
| `--out` | (required) | Output `.epub` path. |
| `--cover` | (optional) | Path to cover image (jpg/png). Recommended 1600×2560 for Apple Books. |
| `--language` | `en` | BCP-47 code; `th` for Thai. |
| `--description` | (optional) | Back-cover blurb (shown in some readers). |
| `--isbn` | (optional) | ISBN if you have one; auto-generates a UUID otherwise. |

## What's supported in chapter markdown

The built-in markdown→XHTML pass is intentionally small (no external deps):

| Markdown | Renders as |
|---|---|
| `# H1` ... `###### H6` | `<h1>` ... `<h6>` |
| `**bold**` `*italic*` | `<strong>` `<em>` |
| `> blockquote` | `<blockquote>` |
| `- list` / `* list` / `1. list` | `<ul>`, `<ol>` |
| `[text](url)` | `<a href="url">text</a>` |
| ` ``` code block ``` ` | `<pre><code>` |
| `` `inline code` `` | `<code>` |
| `---` | `<hr>` |
| Plain paragraphs (blank-line separated) | `<p>` |

For richer formatting (tables, footnotes, images-with-captions), use pandoc to convert each chapter to XHTML first, then drop the resulting `.xhtml` files into `chapters-dir` instead of `.md`. The script reads both.

## Validation

After build, the script runs three checks:

1. **EPUB structure**: required files present (`mimetype`, `META-INF/container.xml`, `OEBPS/content.opf`, `OEBPS/toc.ncx`).
2. **OPF manifest**: every chapter file referenced in `<manifest>` and `<spine>`.
3. **File integrity**: ZIP loads without errors.

If you have `epubcheck` installed (`brew install epubcheck`), the script will *also* invoke it and report; otherwise it's silent. The internal checks alone catch ~90% of problems.

## Output

A single `.epub` file at `--out`. The script prints the path on success. Open with **Apple Books** (drag the `.epub` onto the dock icon) to verify visually, or upload to your KDP/Apple Books/Kobo dashboard.

## Verification

```bash
# Smoke test with a tiny tree
mkdir -p /tmp/test-epub/chapters
cat > /tmp/test-epub/chapters/01-hello.md <<'EOF'
# Hello

This is a test chapter.
EOF

python3 ~/.openclaw/skills/epub-publisher/scripts/build.py \
  --title "Test Book" --author "Test Author" \
  --chapters-dir /tmp/test-epub/chapters \
  --out /tmp/test-epub/test.epub
# Expected: prints /tmp/test-epub/test.epub on success.

# Or run the script's own self-check:
python3 ~/.openclaw/skills/epub-publisher/scripts/build.py --self-test
```
