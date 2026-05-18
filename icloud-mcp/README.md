# icloud-mcp

Local MCP server for Apple iCloud Calendar (CalDAV) and Mail (IMAP). Written in Rust.

Read + create-only by design:

- Calendars: list, list events, get one event, search, create event.
- Mail: list folders, search, get message. Draft creation goes through IMAP APPEND to the Drafts folder - there is no SMTP transport, so the server cannot send mail. The user reviews each draft and sends it manually in iCloud Mail.

## Quick start

Three steps from a clean Claude Code session:

```
/plugin marketplace add nikolaypavlov/claude-skills
/plugin install icloud-mcp
/icloud-mcp:setup
```

What happens:

1. On install, a SessionStart hook downloads the prebuilt binary for your platform (darwin/linux, arm64/x64). No Rust toolchain required.
2. `/icloud-mcp:setup` walks you through generating an Apple app-specific password, captures it, stores it in the macOS Keychain (or `.envrc` on Linux), and verifies the connection with one IMAP login and one CalDAV bootstrap.
3. Ask in chat: `list my iCloud calendars`, `search mail from <someone>`, `draft an email about <topic>`.

Prerequisites:

- An Apple ID with two-factor authentication enabled (required to mint app-specific passwords).
- macOS (arm64 or x64) or Linux (x64 or arm64). Other platforms fall back to building from source if `cargo` is in PATH.

## Installing in Claude Desktop (macOS)

Claude Desktop (the macOS app from claude.ai/download) does not have a plugin marketplace - MCP servers are added by editing `~/Library/Application Support/Claude/claude_desktop_config.json` directly. The five steps below get icloud-mcp running there without ever leaving the terminal.

### 1. Download the binary

Pick the archive that matches your CPU:

```
# Apple Silicon (M1-M4):
curl -L -o /tmp/icloud-mcp.tar.gz \
  https://github.com/nikolaypavlov/claude-skills/releases/download/icloud-mcp-v0.3.3/icloud-mcp-v0.3.3-aarch64-apple-darwin.tar.gz

# Intel:
curl -L -o /tmp/icloud-mcp.tar.gz \
  https://github.com/nikolaypavlov/claude-skills/releases/download/icloud-mcp-v0.3.3/icloud-mcp-v0.3.3-x86_64-apple-darwin.tar.gz
```

Optional but recommended - verify the SHA256:

```
curl -sL https://github.com/nikolaypavlov/claude-skills/releases/download/icloud-mcp-v0.3.3/SHA256SUMS \
  | grep apple-darwin
shasum -a 256 /tmp/icloud-mcp.tar.gz
```

The two checksums for your target must match.

### 2. Install and clear quarantine

```
mkdir -p ~/.local/bin
tar -C ~/.local/bin -xzf /tmp/icloud-mcp.tar.gz
chmod +x ~/.local/bin/icloud-mcp
xattr -d com.apple.quarantine ~/.local/bin/icloud-mcp 2>/dev/null
```

The `xattr -d` step is required. The binary is not code-signed, so without it Launch Services blocks Claude Desktop from spawning the server.

### 3. Generate an app-specific password and store it in Keychain

1. Open https://account.apple.com/account/manage and sign in.
2. Select the App-Specific Passwords tab.
3. Click Generate password, name it `icloud-mcp`, copy the 16-character code (with dashes).
4. Store it in Keychain via stdin so the password never appears in shell history:

   ```
   printf '%s' 'abcd-efgh-ijkl-mnop' | security add-generic-password \
       -s icloud-mcp \
       -a "you@icloud.com" \
       -U \
       -w
   ```

   Replace the password and `you@icloud.com` with your real values. `-U` updates the entry if it already exists.

### 4. Wire it into Claude Desktop config

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`. If the file does not exist, create it. Add `icloud` under `mcpServers`:

```
{
  "mcpServers": {
    "icloud": {
      "command": "/Users/<YOUR-USERNAME>/.local/bin/icloud-mcp",
      "env": {
        "APPLE_ID": "you@icloud.com"
      }
    }
  }
}
```

- `command` must be a fully-resolved path (no `~`). Run `echo "$HOME/.local/bin/icloud-mcp"` to get the exact string.
- `APPLE_ID` is needed so the binary knows which Keychain entry to look up.
- `APPLE_APP_PASSWORD` does NOT need to go in this JSON - the binary's macOS Keychain fallback reads it from the entry you created in step 3.

Quick pre-flight before restarting the app:

```
APPLE_ID="you@icloud.com" ~/.local/bin/icloud-mcp --probe
```

A response with `"ok": true` and non-zero counts under `imap` and `caldav` confirms everything is set up.

### 5. Restart Claude Desktop

Use Cmd-Q (full quit, not just close window) and relaunch. The MCP server should connect on the next session. Try in chat: "list my iCloud calendars".

### Troubleshooting

- `AUTHENTICATIONFAILED`: the app-specific password is wrong or has been revoked. Regenerate it and re-run the `security add-generic-password` command (still with `-U`) to overwrite the Keychain entry.
- Gatekeeper prompt or server fails to start: run `xattr -cr ~/.local/bin/icloud-mcp` to clear all extended attributes, then try again.
- Logs: Help -> View Logs in Claude Desktop, or `tail -f ~/Library/Logs/Claude/mcp*.log` in a terminal.

When Anthropic ships plugin-marketplace support in Claude Desktop, this whole flow collapses into a one-line install. For now this is the supported path.

## Architecture

```
                Claude Code
                    |
                    | stdio (JSON-RPC, rmcp 0.16)
                    v
          +------------------+
          | icloud-mcp (Rust)|
          +---------+--------+
                    |
        +-----------+-----------+
        |                       |
        v                       v
   CalDAV (libdav)         IMAP (async-imap + tokio-rustls)
   caldav.icloud.com       imap.mail.me.com:993
   - principal             - list folders
   - calendar-home-set     - search (FROM/SUBJECT/SINCE/...)
   - REPORT calendar-query - UID FETCH RFC822 (parsed via mail-parser,
   - PUT VEVENT              HTML -> markdown via html2md)
                           - APPEND <draft> with \Draft flag
                    ^
                    |
        Basic auth: APPLE_ID + APPLE_APP_PASSWORD
        (env vars, or macOS Keychain on macOS)
```

## Tools

| Tool                       | Behavior                                                            |
|----------------------------|---------------------------------------------------------------------|
| `calendar_list_calendars`  | All iCloud calendars (id, name, color).                             |
| `calendar_list_events`     | Events in a calendar between two RFC 3339 timestamps.               |
| `calendar_get_event`       | Full event by UID, including raw iCalendar.                         |
| `calendar_search_events`   | Substring match across SUMMARY/LOCATION. Default window +/- months. |
| `calendar_create_event`    | Create a VEVENT (organizer auto-set to your Apple ID).              |
| `mail_list_folders`        | IMAP folders with special-use tags (Drafts/Sent/Trash/...).         |
| `mail_search`              | UID search (FROM/SUBJECT/TEXT/SINCE/BEFORE/UNSEEN), newest first.   |
| `mail_get_message`         | Full or partial message (capped at `max_bytes`, default 512 KB). Returns `truncated`, `total_size_bytes`, attachment metadata (`name`/`mime`/`size`). HTML bodies are converted to markdown (off-thread for >100 KB). |
| `mail_create_draft`        | Append RFC 822 to Drafts with `\Draft` flag. Does NOT send.         |
| `auth_status`              | Diagnostic. Returns whether credentials are loaded, their source, and last-OK timestamps for IMAP/CalDAV. Use when other tools fail. |

All timestamps are RFC 3339 UTC, e.g. `2026-05-14T09:00:00Z`.

## Diagnostics

If a tool fails and you are not sure why:

1. Call the `auth_status` MCP tool from chat. The JSON tells you whether credentials are loaded, where they were sourced from (env vs Keychain), and when each subsystem last succeeded.
2. Run the binary in `--probe` mode directly. It tries one IMAP login and one CalDAV bootstrap, then prints a JSON diagnostic to stdout:

   ```
   "${CLAUDE_PLUGIN_ROOT}/target/release/icloud-mcp" --probe
   ```

   Useful response shapes:
   - `{"ok": true, "imap": {"folders": 18}, "caldav": {"calendars": 4}}` - login works.
   - `{"imap": {"ok": false, "error": "...AUTHENTICATIONFAILED..."}}` - password is wrong or revoked.
   - `{"ok": false, "stage": "config"}` - no credentials. Re-run `/icloud-mcp:setup`.

3. Raise log verbosity: `ICLOUD_MCP_LOG=icloud_mcp=debug` (preferred) or `RUST_LOG=debug`. `ICLOUD_MCP_LOG` wins if both are set. Logs go to stderr; stdout is reserved for the MCP protocol.

### macOS env var pitfall

If you launch Claude Code from Finder (not a shell), it does NOT inherit `APPLE_ID` / `APPLE_APP_PASSWORD` set in `~/.zshrc` or similar. Either:

- Use the macOS Keychain path (default in `/icloud-mcp:setup`), which all processes see.
- Run `launchctl setenv APPLE_ID ... && launchctl setenv APPLE_APP_PASSWORD ...` to expose the vars to GUI apps until reboot.

## Error semantics

Tool errors are classified so the client can react meaningfully:

- `invalid_params` -- bad argument or referenced resource does not exist (wrong `calendar_id`, missing event UID, malformed email, CR/LF in IMAP search terms), or the plugin is unconfigured (run `/icloud-mcp:setup`).
- `internal_error` with `transient failure (safe to retry)` prefix -- network timeout, IMAP NOOP failure mid-session, TLS handshake failure. Retrying often resolves it.
- `internal_error` with `auth failed` prefix -- the app-specific password is wrong or has been revoked. Mint a new one.
- `internal_error` otherwise -- permanent server-side or protocol failure.

All network calls (CalDAV requests, IMAP commands, TCP connect, TLS handshake) have explicit timeouts (10-20 s). The IMAP session is pooled across tool calls with a 5-minute idle expiry and revalidated via `NOOP`.

## IMAP search and non-ASCII

`mail_search` accepts non-ASCII (e.g. Cyrillic, accented Latin) in `from`, `subject`, and `text`. When any term contains non-ASCII bytes the server-side query is prefixed with `CHARSET UTF-8` (iCloud accepts this). CR/LF characters in any search term are rejected.

## Advanced: manual installation

If you cannot use the prebuilt binary (no curl, restricted network, unsupported platform), or prefer to build from source:

```
cd icloud-mcp
cargo build --release
```

The binary lands at `icloud-mcp/target/release/icloud-mcp`. The plugin manifest in `.mcp.json` references this path via `${CLAUDE_PLUGIN_ROOT}`. Re-launch Claude Code so it picks up the binary.

### Manual credentials

The `--setup` wizard handles credentials, but if you want to provision them yourself:

Environment variables (any shell):

```
export APPLE_ID="you@icloud.com"
export APPLE_APP_PASSWORD="abcd-efgh-ijkl-mnop"
```

macOS Keychain (preferred on Mac, all processes see it):

```
printf '%s' "abcd-efgh-ijkl-mnop" | security add-generic-password \
    -s icloud-mcp -a "$APPLE_ID" -U -w
```

The trailing `-w` with no argument reads the password from stdin, so it does not end up in shell history. `-U` updates the entry if it already exists.

The server reads `APPLE_APP_PASSWORD` from the env first; if absent it queries the `icloud-mcp` service in the Keychain using `APPLE_ID` as the account.

App-specific password URL:
`https://account.apple.com/account/manage` (select the App-Specific Passwords tab)

## Development

```
cargo fmt              # apply rustfmt (config in rustfmt.toml)
cargo clippy --all-targets   # lint; [lints] in Cargo.toml gates warnings
cargo build --release
cargo test             # unit + integration tests
```

`Cargo.toml` enables `unsafe_code = "forbid"` and `clippy::all = warn`. The release profile uses `lto = "thin"` and `strip = "symbols"`. Integration tests under `tests/` use `httpmock` to stub CalDAV endpoints.

Cross-platform release binaries are produced by `.github/workflows/release-icloud-mcp.yml` on tags matching `icloud-mcp-v*`. The matrix builds for `aarch64-apple-darwin`, `x86_64-apple-darwin`, `x86_64-unknown-linux-gnu`, and `aarch64-unknown-linux-gnu`. macOS binaries target `MACOSX_DEPLOYMENT_TARGET=13.0` for compatibility with older OS versions.

## Dependencies

- `rmcp` - MCP SDK
- `libdav` - CalDAV (hyper + hyper-rustls + tower-http)
- `icalendar` - VEVENT build/parse
- `async-imap` + `tokio-rustls` - IMAP over TLS
- `mail-parser` - RFC 822 parsing
- `lettre` (builder feature only) - draft construction
- `html2md` - HTML to markdown for mail bodies
- `security-framework` (macOS) - Keychain lookup

## Why no SMTP?

Sending email is the only operation that produces irreversible external side-effects (recipients see it, mail relays log it). Drafts are reversible: the user reviews each one in iCloud Mail and chooses whether to send. This matches the "read + create only" scope you set when scaffolding the server.
