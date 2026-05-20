---
description: "Interactive setup for monobank-mcp - ensures the binary is installed and captures the Monobank Personal API token."
allowed-tools: ["Bash", "Read", "Write", "AskUserQuestion"]
---

You are guiding the user through first-time setup of the `monobank-mcp` plugin. The plugin cannot work without a Monobank Personal API token.

Be terse. Each phase should produce one short status line and move on. Do not lecture the user about Monobank or security unless asked.

## Phase 1: Ensure the binary is installed

Run this exact Bash command (single call):

```bash
test -x "${CLAUDE_PLUGIN_ROOT}/target/release/monobank-mcp" \
  || bash "${CLAUDE_PLUGIN_ROOT}/scripts/install-binary.sh"
```

- If the script downloaded or built the binary, report "Binary installed."
- If the binary was already present, report "Binary ready."
- If the script failed, stop and show its stderr to the user. Do not proceed.

Also detect the host platform for later phases:

```bash
uname -s
```

Cache the result (`Darwin` or `Linux`) for Phase 3.

## Phase 2: Capture the token

First, print this exact block to the user (verbatim, in a code fence):

```
1. Open: https://api.monobank.ua/
2. Click "Get a token", scan the QR code with the Monobank app, approve access.
3. Copy the token from the success page (looks like uXXXXXXXX...).
```

Then use AskUserQuestion:

- Question: "Paste your Monobank Personal API token."
- Header: "Mono token"
- Options:
  - `Paste token` - description: "Pick this and paste the token into the Other box."
  - `Cancel setup` - description: "Stop without storing anything."

Validate:
- Strip whitespace.
- Must be non-empty and at least 30 characters.
- If invalid, re-ask once with an inline note explaining the expected shape.

Do NOT echo the token back in subsequent messages.

## Phase 3: Choose where to store it

Build the options list based on the platform detected in Phase 1:

**If Darwin:**

- `macOS Keychain` (recommended) - description: "Stored under service `monobank-mcp`, account `api-token`. Persists across reboots."
- `launchctl setenv` - description: "Sets MONOBANK_TOKEN for all GUI apps until reboot. Useful if you run Claude Code from Finder rather than a terminal."
- `Project .envrc (direnv)` - description: "Writes ./.envrc in the current directory. Requires `direnv allow` after."
- `Print export commands` - description: "Display the export line; you paste it yourself."

**If Linux (or anything non-Darwin):**

- `Project .envrc (direnv)` (recommended)
- `Print export commands`

Use AskUserQuestion with the platform-appropriate option set. Header: `Storage`.

## Phase 4: Execute the storage choice

### macOS Keychain

Use the binary itself, which stores via the `keyring` crate:

```bash
printf '%s' "<token>" | "${CLAUDE_PLUGIN_ROOT}/target/release/monobank-mcp" init --stdin
```

Verify the entry exists:

```bash
security find-generic-password -s monobank-mcp -a api-token -w | wc -c
```

Expect at least 30 (token length + newline). If 0 or 1, re-prompt (Phase 2) and retry.

### launchctl setenv

```bash
launchctl setenv MONOBANK_TOKEN "<token>"
```

Tell the user: "This persists until reboot. To make it permanent, add `launchctl setenv ...` to a launchd plist in ~/Library/LaunchAgents."

### Project .envrc

Use the Write tool to create `./.envrc` with:

```
export MONOBANK_TOKEN="<token>"
```

Then remind the user: "Run `direnv allow` in this directory to activate, and add `.envrc` to `.gitignore` if it isn't already."

### Print export commands

Print this fenced block:

```
export MONOBANK_TOKEN="<token>"
```

Tell the user to paste it into their shell, then re-launch Claude Code so the MCP server picks it up.

## Phase 5: Probe the connection

Run the binary's `--probe` mode with the captured token. The probe attempts one `/personal/client-info` call, then writes a single JSON object to stdout.

```bash
MONOBANK_TOKEN="<token>" "${CLAUDE_PLUGIN_ROOT}/target/release/monobank-mcp" --probe
```

Parse the JSON. Report based on `ok`:

- `ok: true`: "Probe OK. Found N accounts." (use `accounts_count`).
- `ok: false` with error containing `401`, `403`, or `auth failed`: tell the user "Monobank rejected the token. It may have been mistyped or revoked. Generate a fresh one at https://api.monobank.ua/ and re-run /monobank-mcp:setup."
- `ok: false` with `429` or `rate limited`: tell the user "Probe hit Monobank's rate limit - wait 60 seconds and re-run /monobank-mcp:setup, or skip the probe and run `monobank-mcp accounts` from a terminal."
- `ok: false` with other errors: show the full JSON, suggest the user check connectivity.

If the probe failed, stop. Do not declare success.

## Phase 6: Optional cold-start backfill

After a successful probe, ask the user:

- Question: "Backfill historical statements now?"
- Header: "Backfill"
- Options:
  - `Skip` (recommended for first try) - description: "You can run `monobank-mcp backfill --from <date>` later from a terminal."
  - `Last 12 months` - description: "Pulls about 12 chunks at one minute apart = ~12 minutes per account."
  - `Last 24 months` - description: "Up to ~24 minutes per account; the API allows older windows but we cap at 24 months by default."

For `Skip`, just remind the user how to run it later and move on.

For `Last 12 months` / `Last 24 months`, run the corresponding command in the background and tell the user the expected duration:

```bash
"${CLAUDE_PLUGIN_ROOT}/target/release/monobank-mcp" backfill --from "$(date -u -v -<N>m '+%Y-%m-%d' 2>/dev/null || date -u -d '<N> months ago' '+%Y-%m-%d')"
```

(`-v -<N>m` works on macOS; `date -d '<N> months ago'` on Linux.)

The command honours the rate limit (61s between calls) so do not background-poll its status - just tell the user it is running and let them check `monobank-mcp sync` later.

## Phase 7: Confirm and hand off

Print:

```
monobank-mcp is configured.
- Token stored in: <Keychain | launchctl | .envrc | shell>
- Accounts detected: <N>

Try in chat:
  - "list my mono accounts"
  - "sync mono now"  (after PR#3 personal-finance is also installed)

Re-run /monobank-mcp:setup any time you rotate the token.
```

## Safety notes (apply throughout)

- Never log, echo, or store the token in plain text anywhere except the chosen target.
- Never pass the token as a positional argument to a command - pipe via stdin where supported.
- Never write to ~/.zshrc, ~/.bash_profile, or similar without explicit user approval.
- If at any phase the user expresses concern, stop and ask.
