# PDF design system

The visual system for PDF documents produced from a project (proposals, reports, internal plans, briefs). The goal is a single, recognisable look across everything we hand to clients or share internally, anchored to a refined editorial typography stack.

The canonical stylesheet ships with the `pdf-design-system` skill at `assets/pdf-style.css`. Every PDF generated through this system is built from a markdown source plus that stylesheet. Do not fork the CSS per document; extend the system if a real new need shows up. For project-specific tweaks (wordmark, palette), use a thin override CSS in the project (see "Project wordmark" below).

## How to produce a PDF

```
pandoc docs/<source>.md -o /tmp/out.html \
  --standalone \
  --metadata pagetitle="Document title for HTML head" \
  --css="${SKILL_DIR}/assets/pdf-style.css" \
  --embed-resources \
  -V lang=en

weasyprint /tmp/out.html docs/<source>.pdf
```

`${SKILL_DIR}` is the absolute path to the installed `pdf-design-system` skill. If the project has an override file (e.g., `docs/pdf-overrides.css`), append it as a second `--css` flag - CSS cascade applies the override on top of the canonical:

```
--css="${SKILL_DIR}/assets/pdf-style.css" \
--css=docs/pdf-overrides.css \
```

Use `--metadata pagetitle=...` (sets only the HTML `<title>`). Do not use `--metadata title=...` - it injects a duplicate H1 into the body on top of the markdown H1.

Web fonts are fetched at render time from Google Fonts (`@import` in the CSS). The container needs network access during render. Fonts are then embedded into the resulting PDF, so the file is portable.

## Brand foundation

### Colors

The default palette is anchored to a navy/gold/cream brand. Override the CSS custom properties in `:root` if your project uses a different palette - the rest of the system inherits from these tokens.

| Token | Default | Use |
|-------|---------|-----|
| `--navy` | `#1A3D6D` | H1, H2, H3 (when nested), links, page numbers, table header text |
| `--navy-deep` | `#122a4e` | inline code text |
| `--gold` | `#C9A575` | rules above headings, link underlines, code-block left border, hr |
| `--gold-deep` | `#a8854f` | list bullets, ordered numerals |
| `--cream` | `#F9F3E9` | inline code background |
| `--cream-warm` | `#fbf8f1` | code-block background |
| `--ink` | `#181818` | strong/bold text |
| `--text` | `#2d2d2d` | default body text |
| `--muted` | `#707070` | running header, wordmark |
| `--lead` | `#4a4a4a` | h1 lead paragraph, blockquote |
| `--line` | `#d8d2c4` | section divider above H2 |
| `--line-soft` | `#ece6d6` | table row dividers |

Every visible color in the canonical CSS reads from these tokens. Redeclaring a token in an override CSS propagates to every place that uses it. There are no hardcoded hex values outside `:root`.

### Typography

Three families, all variable, all loaded from Google Fonts.

- **Fraunces** (display serif) - distinctive humanist, optical sizes 9-144. Used for H1, H2, H3, table headers, page numbers. The optical-size axis means H1 at 30pt looks sculpted while H3 at 12pt still reads as the same family.
- **Source Serif 4** (text serif) - designed for both screen and print, optical sizes 8-60. Used for body, italic lead paragraphs, H4, table cells.
- **JetBrains Mono** (monospace) - clean and even-weighted. Used for inline code, code blocks, and ASCII diagrams. Ligatures off (so ASCII art renders correctly).

## Type scale

| Element | Family | Size | Weight | Color | Notes |
|---------|--------|------|--------|-------|-------|
| H1 | Fraunces | 30 pt | 600 | Navy | Title only. Gold rule above (2.5em x 2pt). Tight tracking -0.022em |
| H1 lead paragraph | Source Serif 4 italic | 12.5 pt | 400 | Lead | First paragraph after H1. Treated as document subtitle |
| H2 | Fraunces | 16.5 pt | 600 | Navy | Top-level section. Thin gold marker over a 0.5pt line on top |
| H3 | Fraunces | 12 pt | 600 | Ink | Subsection under H2. No decoration |
| H4 | Source Serif 4 | 10.5 pt | 600 | Navy | Rare. Use for paragraph-level labels in long sections |
| Body | Source Serif 4 | 10.5 pt | 400 | Text | Line-height 1.58. Hyphenation on |
| Strong | Source Serif 4 | 10.5 pt | 600 | Ink | For emphasized words, lead-in labels |
| Inline code | JetBrains Mono | 0.86 em | 400 | Navy deep | Cream background, 2px radius |
| Code block | JetBrains Mono | 7.6 pt | 400 | Ink | Cream-warm background, 2pt gold left border, line-height 1.35 |
| Table header | Fraunces uppercase | 8.8 pt | 600 | Navy | Letter-spacing 0.07em. 1.5pt navy bottom border |
| Table cell | Source Serif 4 | 9.8 pt | 400 | Text | 0.5pt line-soft row dividers. Tabular figures from column 2 |
| Page number | Fraunces | 10 pt | 600 | Navy | Bottom right of every page after first |
| Wordmark | Fraunces | 8 pt | 500 | Muted | Uppercase, letter-spacing 0.18em, bottom left. Empty by default; project-specific (see below) |
| Running header | Source Serif 4 italic | 8.5 pt | 400 | Muted | Document title from H1. Top left |

## Hierarchy rules

- One H1 per document. It is the title and runs into the running header automatically (`string-set: doctitle`).
- H2 for top-level sections. Always preceded by a section break (visual: thin gold marker + line).
- H3 for subsections under H2. Don't use H3 outside an H2.
- Don't skip levels (no H1 to H3 jump).
- For short labelled paragraphs use a bold lead-in: `**Label.** Body sentence...`. Don't promote those to H4 unless the section is long enough to need a real subheading.
- Sentence case for headings, never title case ("Why we build it on this stack", not "Why We Build It On This Stack").

## Page setup

- **Format**: A4 (210 x 297 mm)
- **Margins**: 2.4 cm top, 2 cm sides, 2.6 cm bottom
- **First page**: 3.8 cm top margin, no running header, no wordmark, no page number. The title carries the page on its own.
- **Subsequent pages**:
  - Top left: running header (italic title from H1)
  - Bottom left: project wordmark (empty by default - see "Project wordmark" below)
  - Bottom right: page number

The first-page rule keeps title pages clean. Hand-off feel.

## Project wordmark

The bottom-left of every page after the first is reserved for a project wordmark - usually a brand name in small caps. The styling (font, size, letter-spacing, color) is fixed by the design system. The text content is per-project.

Default: empty. The bottom-left margin box is rendered with no visible text.

To set a wordmark for a specific project, override the `--wordmark` custom property in a thin project-local CSS file. No `@import` is needed - the canonical stylesheet is passed as the first `--css` argument and the override file as the second; CSS cascade does the rest.

Create `docs/pdf-overrides.css` in the project:

```css
:root {
  --wordmark: "Acme Co";
}
```

Then render with both stylesheets in order:

```
--css="${SKILL_DIR}/assets/pdf-style.css" \
--css=docs/pdf-overrides.css \
```

Everything not redefined (palette, type scale, page chrome) inherits from the canonical. This is also the right place to override brand colors per project - redeclare any tokens (`--navy`, `--gold`, etc.) inside the same `:root` block.

## Components

### Headings

H1 - tight, large, navy. Gold rule above (2.5em x 2pt) acts as a small typographic mark, not a divider. The H1 sets the running header for the rest of the document via `string-set`.

H2 - the visual cue is a thin gold marker (1.4em x 1.6pt) that sits on top of a full-column 0.5pt line. The marker reads as a sectioning device; the line gives the section breathing room from the previous content. Padding-top + margin-top combine to produce that breath without forcing a page break.

H3 - no decoration. Family-and-color hierarchy alone signals depth.

### Lists

- Unordered lists use an em-dash `—` marker in gold deep (not the default disc bullet). Hanging indent so wrapped lines align under the body, not under the marker.
- Ordered lists use gold-deep Fraunces numerals (size 10pt, weight 700) at the right of the left column. The numeral alignment makes 1-9 line up neatly with 10+ even on the same list.
- Nested lists: same conventions one level deeper. Avoid going past two levels of nesting.

### Tables

Use tables when comparing items across attributes. They beat parallel bullet lists for clarity.

- Header: Fraunces uppercase, navy color, 1.5pt navy bottom border. Reads like a small caption.
- Cells: 0.55em vertical padding. 0.5pt line-soft horizontal dividers between rows.
- Last row gets a 1pt navy border (closes the table).
- Numeric columns get tabular figures automatically (column 2 onward).

### Code blocks

Used for ASCII diagrams, file trees, and any code samples.

- Background: cream-warm `#fbf8f1` (just enough off-white to set apart from the page)
- Left border: 2pt gold (the same accent that marks H1 and H2)
- Font: JetBrains Mono 7.6pt, line-height 1.35, ligatures off
- `page-break-inside: avoid` - code blocks stay together on one page. If a diagram is taller than a page, simplify or split it; do not let it span pages

ASCII diagrams: left-align without leading whitespace. The gold border + cream background already separates them visually; centring with leading spaces wastes width and breaks at narrow column widths.

### Inline code

- Cream background `#F9F3E9`
- JetBrains Mono 0.86em
- 2px border-radius, light padding
- Use for: file paths, function names, env vars, short literal values

### Links

Navy with a gold underline (0.5pt, 2px offset). Underline indicates link without using a different color, which would clash with the navy heading hierarchy.

### Horizontal rule

A short gold line (3em wide, centred, 1px). Use sparingly - it's a "section divider within a section" device, not a section break (H2 already does that).

## Writing conventions for PDF docs

- Title is one short H1 phrase. No subtitle inside the H1 - use the lead paragraph for a one-sentence subtitle.
- Sentence case headings, always.
- Hyphens for ranges and dashes (`5-7 weeks`, not `5–7 weeks`). No em-dashes.
- Straight quotes only.
- Three plain dots if you must use ellipsis. Better: rewrite to avoid it.
- No emoji, no Unicode bullets, no non-breaking spaces.
- ASCII diagrams: narrow enough that 7.6pt Mono fits the column without horizontal overflow. Test by rendering before committing.
- Tables over deep nested bullet lists for comparison content.
- Bold lead-ins for short labelled paragraphs (`**Label.** Body...`). Don't bold full sentences.

## File conventions

| File | Role |
|------|------|
| `${SKILL_DIR}/assets/pdf-style.css` | Canonical stylesheet. Single source of truth, shipped with the skill |
| `docs/pdf-overrides.css` | Optional project override. Redefines `--wordmark` and any color tokens. Passed as second `--css` |
| `docs/<doc-name>.md` | Markdown source (the editable artifact) |
| `docs/<doc-name>.pdf` | Generated output. Regenerate from markdown; never edit directly |

PDFs are committed to the repo so they're shareable from a single link, but the markdown is the source of truth. If the PDF and markdown disagree, regenerate.

## Updating the design system

- Palette or typography changes happen in the skill's `assets/pdf-style.css` and propagate to every PDF on next render.
- Re-render an existing PDF and compare side by side before merging.
- One-off documents do not get one-off CSS overrides. If a real new need appears, add a class to the canonical CSS and document it here.

## Toolchain

- pandoc 3.x for markdown to HTML
- WeasyPrint 68+ for HTML to PDF
- Google Fonts (Fraunces, Source Serif 4, JetBrains Mono) fetched via `@import` and embedded in the PDF
