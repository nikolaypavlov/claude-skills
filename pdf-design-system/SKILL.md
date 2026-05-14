---
name: pdf-design-system
description: This skill should be used when the user needs to convert a markdown document to PDF using the standard PDF design system (navy/gold/cream editorial style with Fraunces, Source Serif 4, JetBrains Mono). Triggers include "convert to PDF", "generate PDF", "render markdown to PDF", "make a PDF report/proposal/brief", "apply PDF design", "PDF style", or any request to produce a styled PDF from markdown. The skill provides the canonical stylesheet, the pandoc + WeasyPrint command, per-project override mechanism, and writing conventions.
version: 0.1.0
---

# PDF design system

Convert a markdown source to a styled PDF using the canonical visual system (navy/gold/cream editorial, Fraunces + Source Serif 4 + JetBrains Mono). The canonical stylesheet lives at `assets/pdf-style.css` inside this skill - do not copy or fork it into the user's project; reference it by absolute path.

For the full design specification (type scale, components, page setup, hierarchy rules), read `references/design-system.md`.

## Prerequisites

Two tools are required: **pandoc** (markdown to HTML) and **WeasyPrint** (HTML to PDF). Both must be on PATH.

### macOS

```bash
brew install pandoc
brew install weasyprint
```

### Linux (Debian / Ubuntu)

```bash
sudo apt-get install pandoc
pipx install weasyprint
```

WeasyPrint also needs Pango, Cairo, and GDK-PixBuf system libraries. On Debian/Ubuntu:

```bash
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
```

### Version requirements

- pandoc 3.x or later (`pandoc --version`)
- WeasyPrint 68 or later (`weasyprint --version`)

### Network access at render time

Web fonts (Fraunces, Source Serif 4, JetBrains Mono) are fetched from Google Fonts via `@import` at the top of the canonical CSS. The render environment must have network access during the WeasyPrint step. Fonts are then embedded into the resulting PDF, so the output file is portable.

If working in a sandboxed container without network access, the user has to either grant network or pre-download the fonts. Stop and ask the user before attempting workarounds.

## Producing a PDF (default)

The default and primary path is to render with only the canonical stylesheet that ships with this skill. No project file is required, no setup is needed beyond installing the tools. **Use this path unless the user explicitly asks for project-specific customization.**

The skill directory path is needed for `--css`. Resolve it once at the start of the session - it is the absolute path to the directory containing this SKILL.md file. Use that path literally in the command below (substitute `${SKILL_DIR}`).

```bash
pandoc <source>.md -o /tmp/out.html \
  --standalone \
  --metadata pagetitle="Document title for HTML head" \
  --css="${SKILL_DIR}/assets/pdf-style.css" \
  --embed-resources \
  -V lang=en

weasyprint /tmp/out.html <source>.pdf
```

**Important flags:**

- `--metadata pagetitle="..."` sets only the HTML `<title>`. Never use `--metadata title=...` - it injects a duplicate H1 into the body on top of the markdown H1.
- `--standalone` produces a complete HTML document with `<head>` so the CSS link applies.
- `--embed-resources` inlines images and other assets into the HTML.
- `-V lang=en` sets the document language. Change for non-English documents (e.g., `-V lang=uk`).

After rendering, verify the PDF opens, check that the first page has no running header / wordmark / page number, and that subsequent pages do.

**Do not auto-create or auto-use a project override file**. If `docs/pdf-overrides.css` happens to already exist in the project, surface it to the user and ask whether they want it applied - do not silently include it.

## Per-project customization (opt-in)

This is a separate, explicit workflow. Trigger it only when the user asks for one of:

- a project wordmark in the bottom-left margin
- a brand-specific palette (override `--navy`, `--gold`, etc.)
- any other token-level tweak

**Use the slash command `/pdf-design-system:init`** to scaffold `docs/pdf-overrides.css`. The command:

1. Prompts for a wordmark (or takes it as an argument)
2. Asks whether to override any palette tokens, then collects values
3. Writes a minimal `:root`-only CSS file at `docs/pdf-overrides.css`
4. Prints the render command with both `--css` flags

Do not handwrite the override file yourself - use the command so the format and scope rules stay consistent.

Once the file exists, the render command takes two `--css` flags in this order:

```bash
pandoc <source>.md -o /tmp/out.html \
  --standalone \
  --metadata pagetitle="Document title" \
  --css="${SKILL_DIR}/assets/pdf-style.css" \
  --css=docs/pdf-overrides.css \
  --embed-resources \
  -V lang=en
```

Order matters: canonical first, override second. CSS cascade applies the override on top of the canonical. Everything not redefined (type scale, page chrome, components) inherits unchanged.

### Tokens available for override

Defined in `assets/pdf-style.css`:

- `--wordmark` - text in the bottom-left margin (default: empty string)
- `--navy`, `--navy-deep` - primary heading and accent colors
- `--gold`, `--gold-deep` - rules, markers, list bullets
- `--cream`, `--cream-warm` - inline-code and code-block backgrounds
- `--line`, `--line-soft` - section dividers and table row dividers
- `--ink`, `--text`, `--muted`, `--lead` - text colors

Every visible color in the canonical CSS reads from one of these tokens, so an override at `:root` propagates everywhere it is used.

### Override scope rule

The project override file must contain only `:root` token redeclarations. Do not put element selectors (`h1`, `h2`, `pre`, `table`, etc.) or `@page` rules in the override - that constitutes forking the design system, which the rest of the system is built to prevent. If a real new need appears that the tokens can't express, add it to the canonical CSS and document it in `references/design-system.md` instead.

## Writing conventions for source markdown

When the user is **writing** the markdown source (not just rendering existing markdown), follow these rules:

- One H1 per document. The H1 is the title; the first paragraph after it becomes the italic lead/subtitle.
- Sentence case headings always ("Why we build it on this stack", not "Why We Build It On This Stack").
- No H1 to H3 jumps. H3 only inside an H2.
- Hyphens for ranges and dashes (`5-7 weeks`). No em-dashes.
- Straight quotes only. Three plain dots for ellipsis (or rewrite).
- No emoji, no Unicode bullets, no non-breaking spaces.
- Bold lead-ins for labelled paragraphs: `**Label.** Body sentence...`
- Tables over deep nested bullet lists for comparison content.
- ASCII diagrams: left-align without leading whitespace; the gold border + cream background already separate them. Narrow enough that 7.6pt Mono fits the column.

See `references/design-system.md` for the full set of rules and the rationale.

## File layout

| Path | Role |
|------|------|
| `${SKILL_DIR}/assets/pdf-style.css` | Canonical stylesheet, single source of truth |
| `${SKILL_DIR}/references/design-system.md` | Full design specification |
| `${SKILL_DIR}/examples/sample.pdf` | Sample rendered output |
| `docs/<doc-name>.md` (in user project) | Markdown source - the editable artifact |
| `docs/<doc-name>.pdf` (in user project) | Generated output - regenerate from markdown |
| `docs/pdf-overrides.css` (in user project, optional) | Per-project tokens override |

PDFs are committed to the user's repo so they are shareable from a single link, but the markdown is the source of truth. If the PDF and markdown disagree, regenerate.

## Updating the design system

Palette or typography changes happen in `assets/pdf-style.css` inside this skill and propagate to every PDF on next render. Bump the skill version in `.claude-plugin/marketplace.json` and re-render an existing PDF as a sanity check before pushing.

One-off documents do not get one-off CSS overrides. If a real new need appears, add a class to the canonical CSS and document it in `references/design-system.md`.
