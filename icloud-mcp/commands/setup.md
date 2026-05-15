---
description: "Interactive setup for icloud-mcp - ensures the binary is installed and captures Apple ID credentials."
allowed-tools: ["Bash", "Read", "Write", "AskUserQuestion"]
---

You are guiding the user through first-time setup of the `icloud-mcp` plugin. This is the only auth path - the plugin cannot work without an Apple ID and an app-specific password.

Be terse. Each phase should produce one short status line and move on. Do not lecture the user about iCloud or security unless asked.

## Phase 1: Ensure the binary is installed

Run this exact Bash command (single call):

```bash
test -x "${CLAUDE_PLUGIN_ROOT}/target/release/icloud-mcp" \
  || bash "${CLAUDE_PLUGIN_ROOT}/scripts/install-binary.sh"
```

- If the script downloaded or built the binary, report "Binary installed."
- If the binary was already present, report "Binary ready."
- If the script failed, stop and show its stderr to the user. Do not proceed.

Also detect the host platform for later phases:

```bash
uname -s
```

Cache the result (`Darwin` or `Linux`) for Phase 4.

## Phase 2: Capture the Apple ID

Use AskUserQuestion:

- Question: "What's the email of your iCloud account?"
- Header: "Apple ID"
- Options:
  - `Enter Apple ID email` - description: "Pick this and type your full email (e.g. you@icloud.com) in the Other box."
  - `Cancel setup` - description: "Stop without making changes."

If the user picks Cancel, stop. Otherwise capture the email they typed via the Other field.

Validate:
- Must contain `@`.
- No spaces.
- If validation fails, re-ask once with the same options and an inline note in the question.

## Phase 3: Capture the app-specific password

First, print this exact block to the user (verbatim, in a code fence):

```
1. Open: https://account.apple.com/sign-in-security/app-passwords
2. Sign in if prompted, then click "Generate password".
3. Name the password "icloud-mcp" and copy the 16-character code (with dashes).
```

Then AskUserQuestion:

- Question: "Paste the 16-character app-specific password (e.g. abcd-efgh-ijkl-mnop)."
- Header: "App password"
- Options:
  - `Paste password` - description: "Pick this and paste the password into the Other box."
  - `Cancel setup` - description: "Stop without storing anything."

Validate:
- Strip whitespace.
- After stripping non-alphanumeric, expect 16 characters.
- If invalid, re-ask once with an inline note explaining the expected shape.

Do NOT echo the password back to the user in subsequent messages.

## Phase 4: Choose where to store the credentials

Build the options list based on the platform detected in Phase 1:

**If Darwin:**

- `macOS Keychain` (recommended) - description: "Stored under service `icloud-mcp`, visible to the MCP server but not to other apps. Survives reboot."
- `launchctl setenv` - description: "Sets APPLE_ID and APPLE_APP_PASSWORD for all GUI apps until reboot. Use if you run Claude Code from Finder rather than a terminal."
- `Project .envrc (direnv)` - description: "Writes ./.envrc in the current directory. Requires `direnv allow` after."
- `Print export commands` - description: "Display the export lines; you paste them yourself."

**If Linux (or anything non-Darwin):**

- `Project .envrc (direnv)` (recommended)
- `Print export commands`

Use AskUserQuestion with the platform-appropriate option set. Header: `Storage`.

## Phase 5: Execute the storage choice

Take the user's choice and run the corresponding Bash. Substitute `$APPLE_ID` and `$APPLE_PASSWORD` with the captured values via shell heredoc/stdin so the password does NOT appear on the command line where possible.

### macOS Keychain

```bash
APPLE_ID="<email>"
printf '%s' "<password>" | security add-generic-password \
  -s icloud-mcp \
  -a "$APPLE_ID" \
  -U \
  -w
```

The `-U` flag updates if the entry already exists. The password is read from stdin (the trailing `-w` with no value).

### launchctl setenv

```bash
launchctl setenv APPLE_ID "<email>"
launchctl setenv APPLE_APP_PASSWORD "<password>"
```

After running, tell the user: "These vars persist until reboot. To make them permanent, add `launchctl setenv ...` to ~/Library/LaunchAgents/<your-plist>.plist."

### Project .envrc

Use the Write tool to create `./.envrc` with:

```
export APPLE_ID="<email>"
export APPLE_APP_PASSWORD="<password>"
```

Then remind the user: "Run `direnv allow` in this directory to activate, and add `.envrc` to `.gitignore` if it isn't already."

### Print export commands

Print this fenced block:

```
export APPLE_ID="<email>"
export APPLE_APP_PASSWORD="<password>"
```

Tell the user to paste them into their shell, then re-launch Claude Code so the MCP server picks them up.

## Phase 6: Probe the connection

Run the binary's `--probe` mode with the captured credentials. The probe attempts one IMAP login and one CalDAV bootstrap, then writes a single JSON object to stdout.

```bash
APPLE_ID="<email>" APPLE_APP_PASSWORD="<password>" \
  "${CLAUDE_PLUGIN_ROOT}/target/release/icloud-mcp" --probe
```

Parse the JSON. Report based on `ok`:

- `ok: true`: "Probe OK. Found N folders, M calendars." (use values from `imap.folders` and `caldav.calendars`).
- `ok: false` with `imap.ok: false` and error matching `AUTHENTICATIONFAILED`:
  "Apple rejected the password. It may have been mistyped or revoked. Generate a new one at https://account.apple.com/sign-in-security/app-passwords and re-run /icloud-mcp:setup."
- `ok: false` with other errors: show the full JSON, suggest the user check connectivity.

If the probe failed, stop. Do not declare success.

## Phase 7: Confirm and hand off

On probe success, print:

```
icloud-mcp is configured.
- Apple ID: <email>
- Stored in: <Keychain | launchctl | .envrc | shell>
- Folders detected: <N>
- Calendars detected: <M>

Try in chat:
  - "list my iCloud calendars"
  - "search mail from <someone>"
  - "draft an email to <someone> about <topic>"

Re-run /icloud-mcp:setup any time you rotate the app-specific password.
```

If credentials were stored via Keychain or .envrc, the MCP server will pick them up on the next session. If they were stored via launchctl or printed, the user may need to restart Claude Code.

## Safety notes (apply throughout)

- Never log, echo, or store the password in plain text anywhere except the chosen target.
- Never run `security add-generic-password -w <password>` with the password as a positional argument - always pipe through stdin.
- Never write to ~/.zshrc, ~/.bash_profile, or similar without explicit user approval.
- If at any phase the user expresses concern, stop and ask.
