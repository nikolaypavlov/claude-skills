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

Restart Claude Code if needed. The MCP server starts automatically when Claude Code loads the plugin.

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
| `mail_get_message`         | Full message; HTML body converted to markdown.                      |
| `mail_create_draft`        | Append RFC 822 to Drafts with `\Draft` flag. Does NOT send.         |

All timestamps are RFC 3339 UTC, e.g. `2026-05-14T09:00:00Z`.

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

To raise log verbosity, set `ICLOUD_MCP_LOG=icloud_mcp=debug` (or pass `RUST_LOG=debug` to the binary directly). Logs go to stderr; stdout is reserved for the MCP protocol.

## Why no SMTP?

Sending email is the only operation that produces irreversible external side-effects (recipients see it, mail relays log it). Drafts are reversible: the user reviews each one in iCloud Mail and chooses whether to send. This matches the "read + create only" scope you set when scaffolding the server.
