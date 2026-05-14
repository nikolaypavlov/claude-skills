---
description: "Scaffold a per-project pdf-overrides.css for the PDF design system (wordmark and optional palette tokens)"
argument-hint: "[wordmark text]"
allowed-tools: ["Bash", "Read", "Write", "AskUserQuestion"]
---

You are scaffolding a per-project override file for the `pdf-design-system` skill. The canonical stylesheet stays inside the skill and is used by default. This command creates a thin local CSS that redefines only the `:root` tokens the project wants to change. The default rendering already works without this file - run this only when the user explicitly wants project-specific customization.

## Phase 1: Locate the target path

Default target: `docs/pdf-overrides.css` relative to the current working directory.

1. Check whether `docs/` exists. If not, ask the user to confirm creating it.
2. Check whether `docs/pdf-overrides.css` already exists.
   - If it does, ask the user via AskUserQuestion:
     - **Overwrite** - replace with new content from this run
     - **Edit in place** - read it, show current values, let user adjust
     - **Cancel** - stop without changes
   - Do not silently overwrite.

## Phase 2: Collect the wordmark

The wordmark is the small caps text in the bottom-left of every page after the first. Empty by default.

1. If the user passed an argument to this command, treat it as the wordmark text and confirm.
2. Otherwise, use AskUserQuestion:
   - Question: "What wordmark text do you want in the bottom-left of pages? (leave empty for none)"
   - Header: "Wordmark"
   - Options:
     - "Set a project wordmark"
     - "Leave empty (default)"
   - If the user picks "Set a project wordmark", capture the text via a follow-up free-text answer.

Trim whitespace. Reject newlines. Allow any printable text (project name like "Acme Co", "MyCo Research", etc.). Length sanity check: warn if longer than 30 characters; the bottom-left margin box has limited width.

## Phase 3: Decide whether to customize the palette

Ask via AskUserQuestion:
- Question: "Do you want to override any color tokens (e.g. brand navy, accent gold)?"
- Header: "Palette"
- Options:
  - "No, keep the default palette" (default)
  - "Yes, override some tokens"

If the user picks "No", skip to Phase 5.

## Phase 4: Collect palette overrides

If the user wants to override tokens, use AskUserQuestion with `multiSelect: true`:

- Question: "Which tokens do you want to override? (you'll set values one by one)"
- Header: "Tokens"
- Options (label, description):
  - `--navy` - "Primary heading/link color. Default `#1A3D6D`"
  - `--gold` - "Accent rules and markers. Default `#C9A575`"
  - `--cream` - "Inline code background. Default `#F9F3E9`"
  - `--ink` - "Strong/bold text. Default `#181818`"
  - `--text` - "Default body text. Default `#2d2d2d`"

(These are the most commonly overridden. If the user needs a less common token like `--navy-deep`, `--gold-deep`, `--cream-warm`, `--lead`, `--muted`, `--line`, `--line-soft`, ask after the multi-select if they need additional tokens beyond this list.)

For each selected token, prompt for a value. Validate:
- Must start with `#`
- Must be 3, 4, 6, or 8 hex digits after the `#`
- Reject anything else with a clear error and re-ask

If the user provides a value that fails validation twice, stop and let them fix and re-run.

## Phase 5: Write the file

Compose the override CSS. The file must contain only a single `:root` block - no element selectors, no `@page` rules, no `@import`. This is the override scope rule from the design system.

Template:

```css
:root {
  --wordmark: "<text>";
  --navy: <value>;
  --gold: <value>;
}
```

Rules:
- Always include `--wordmark`, even if empty (`""`)
- Include only the tokens the user chose to override
- Two-space indent (matches the canonical CSS style)
- Single trailing newline

Write to `docs/pdf-overrides.css`. If `docs/` does not exist, create it first.

## Phase 6: Report and show the render command

Print a short confirmation:
- The path written
- The tokens set (token name and new value)
- The exact pandoc command line the user should now use, with both `--css` flags. Substitute `${SKILL_DIR}` with the absolute path to this skill's directory (the directory containing this command's parent SKILL.md).

Example confirmation:

```
Wrote docs/pdf-overrides.css with:
  --wordmark: "Acme Co"
  --navy: #0F2E5C

Render command:
  pandoc <source>.md -o /tmp/out.html \
    --standalone \
    --metadata pagetitle="<title>" \
    --css="<SKILL_DIR>/assets/pdf-style.css" \
    --css=docs/pdf-overrides.css \
    --embed-resources \
    -V lang=en
  weasyprint /tmp/out.html <source>.pdf
```

Do not run the render yourself. The user runs it when they have a markdown source ready.
