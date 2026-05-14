# icloud-mcp

Local MCP server for Apple iCloud Calendar (CalDAV) and Mail (IMAP). Written in Rust.

Read + create-only by design:

- Calendars: list, list events, get one event, search, create event.
- Mail: list folders, search, get message. Draft creation goes through IMAP APPEND to the Drafts folder - there is no SMTP transport, so the server cannot send mail. The user reviews each draft and sends it manually in iCloud Mail.

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

## Prerequisites

- macOS or Linux. Keychain fallback for credentials is macOS-only.
- Rust toolchain (1.86+, edition 2021 is fine).
- An Apple ID with two-factor authentication enabled (required to mint app-specific passwords).
- App-specific password: https://account.apple.com -> Sign-In and Security -> App-Specific Passwords -> Generate. Use the 16-character output, including dashes.

## Setup

### 1. Build the binary

```
cd icloud-mcp
cargo build --release
```

The binary lands at `icloud-mcp/target/release/icloud-mcp`. The plugin manifest in `.mcp.json` references this path via `${CLAUDE_PLUGIN_ROOT}`.

### 2. Provide credentials

You can use environment variables or, on macOS, the Keychain. Both are checked in that order.

Environment variables (any shell):

```
export APPLE_ID="you@icloud.com"
export APPLE_APP_PASSWORD="abcd-efgh-ijkl-mnop"
```

macOS Keychain (preferred on Mac):

```
security add-generic-password \
    -s icloud-mcp \
    -a "$APPLE_ID" \
    -w "abcd-efgh-ijkl-mnop"
```

The server reads `APPLE_APP_PASSWORD` from the env first; if absent it queries the `icloud-mcp` service in the Keychain using `APPLE_ID` as the account.

### 3. Activate the plugin

From any Claude Code session:

```
/plugin marketplace add nikolaypavlov/claude-skills
/plugin install icloud-mcp
```

The MCP server starts automatically when Claude Code loads the plugin.

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

All timestamps are RFC 3339 UTC, e.g. `2026-05-14T09:00:00Z`.

## Development

```
cargo fmt              # apply rustfmt (config in rustfmt.toml)
cargo clippy --all-targets   # lint; [lints] in Cargo.toml gates warnings
cargo build --release
```

`Cargo.toml` enables `unsafe_code = "forbid"` and `clippy::all = warn`. The release profile uses `lto = "thin"` and `strip = "symbols"`.

## Dependencies

- `rmcp` - MCP SDK
- `libdav` - CalDAV (hyper + hyper-rustls + tower-http)
- `icalendar` - VEVENT build/parse
- `async-imap` + `tokio-rustls` - IMAP over TLS
- `mail-parser` - RFC 822 parsing
- `lettre` (builder feature only) - draft construction
- `html2md` - HTML to markdown for mail bodies
- `security-framework` (macOS) - Keychain lookup

## Troubleshooting

`APPLE_ID env var not set ...`
- Export the env var, or add a Keychain entry as shown above.

`IMAP login: ...AUTHENTICATIONFAILED`
- The app-specific password is wrong, was revoked, or 2FA is disabled. Mint a fresh one at account.apple.com.

`CalDAV service discovery (caldav.icloud.com): ...`
- The CalDAV endpoint is unreachable, or your Apple account has restricted CalDAV access (rare). Verify with `curl -u "$APPLE_ID:$APPLE_APP_PASSWORD" https://caldav.icloud.com/`.

`could not locate Drafts folder ...`
- Your iCloud Drafts folder has been renamed. Provide a literal name override via a future flag, or rename it back to `Drafts` in iCloud Mail.

To raise log verbosity, set `ICLOUD_MCP_LOG=icloud_mcp=debug` (preferred) or `RUST_LOG=debug`. `ICLOUD_MCP_LOG` wins if both are set. Logs go to stderr; stdout is reserved for the MCP protocol.

## Error semantics

Tool errors are classified so the client can react meaningfully:

- `invalid_params` -- bad argument or referenced resource does not exist (wrong `calendar_id`, missing event UID, malformed email, CR/LF in IMAP search terms). Fix the arguments and retry.
- `internal_error` with `transient failure (safe to retry)` prefix -- network timeout, IMAP NOOP failure mid-session, TLS handshake failure. Retrying often resolves it.
- `internal_error` with `auth failed` prefix -- the app-specific password is wrong or has been revoked. Mint a new one.
- `internal_error` otherwise -- permanent server-side or protocol failure.

All network calls (CalDAV requests, IMAP commands, TCP connect, TLS handshake) have explicit timeouts (10-20 s). The IMAP session is pooled across tool calls with a 5-minute idle expiry and revalidated via `NOOP`.

## IMAP search and non-ASCII

`mail_search` accepts non-ASCII (e.g. Cyrillic, accented Latin) in `from`, `subject`, and `text`. When any term contains non-ASCII bytes the server-side query is prefixed with `CHARSET UTF-8` (iCloud accepts this). CR/LF characters in any search term are rejected.

## Why no SMTP?

Sending email is the only operation that produces irreversible external side-effects (recipients see it, mail relays log it). Drafts are reversible: the user reviews each one in iCloud Mail and chooses whether to send. This matches the "read + create only" scope you set when scaffolding the server.
