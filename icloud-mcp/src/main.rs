use std::sync::Arc;

use chrono::{DateTime, Duration, Utc};
use rmcp::{
    handler::server::wrapper::Parameters,
    model::{CallToolResult, Content, ProtocolVersion, ServerCapabilities, ServerInfo},
    schemars, tool, tool_handler, tool_router,
    transport::stdio,
    ErrorData as McpError, ServerHandler, ServiceExt,
};
use tokio::sync::Mutex;
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

use icloud_mcp::caldav;
use icloud_mcp::config::Config;
use icloud_mcp::error::{invalid_params, to_mcp};
use icloud_mcp::imap_client::{DraftParams, ImapClient, SearchCriteria};

// ---------- tool argument types ----------

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct ListEventsArgs {
    /// Calendar id (the `id` field from calendar_list_calendars).
    pub calendar_id: String,
    /// Inclusive RFC 3339 lower bound (UTC), e.g. "2026-05-14T00:00:00Z".
    pub start: String,
    /// Exclusive RFC 3339 upper bound (UTC), e.g. "2026-05-21T00:00:00Z".
    pub end: String,
}

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct GetEventArgs {
    pub calendar_id: String,
    /// Event UID from calendar_list_events, or its full .ics href.
    pub uid: String,
}

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct SearchEventsArgs {
    /// Case-insensitive substring matched against SUMMARY and LOCATION.
    pub query: String,
    /// RFC 3339 lower bound. Defaults to 30 days ago.
    #[serde(default)]
    pub start: Option<String>,
    /// RFC 3339 upper bound. Defaults to 90 days ahead.
    #[serde(default)]
    pub end: Option<String>,
    /// Limit to one calendar; otherwise searches all.
    #[serde(default)]
    pub calendar_id: Option<String>,
}

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct CreateEventArgs {
    pub calendar_id: String,
    pub title: String,
    /// RFC 3339 start datetime (UTC).
    pub start: String,
    /// RFC 3339 end datetime (UTC). Must be after start.
    pub end: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub location: Option<String>,
    /// Email addresses to invite as ATTENDEEs.
    #[serde(default)]
    pub attendees: Vec<String>,
}

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct MailSearchArgs {
    /// IMAP folder, typically "INBOX". Use mail_list_folders for the full list.
    pub folder: String,
    #[serde(default)]
    pub from: Option<String>,
    #[serde(default)]
    pub subject: Option<String>,
    /// Full-text search inside the message.
    #[serde(default)]
    pub text: Option<String>,
    /// RFC 3339 lower bound on INTERNALDATE (date precision only - IMAP SINCE).
    #[serde(default)]
    pub since: Option<String>,
    /// RFC 3339 upper bound on INTERNALDATE (IMAP BEFORE).
    #[serde(default)]
    pub before: Option<String>,
    #[serde(default)]
    pub unseen: bool,
    /// Max messages to return (most recent first). Default 25.
    #[serde(default = "default_limit")]
    pub limit: u32,
}

fn default_limit() -> u32 {
    25
}

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct MailGetArgs {
    pub folder: String,
    /// IMAP UID (NOT sequence number) returned by mail_search.
    pub uid: u32,
    /// Cap on body bytes pulled from the server. Default 524288 (512 KB).
    /// When the message exceeds this, headers + first body part are fetched
    /// and `truncated: true` is returned along with the full
    /// `total_size_bytes` and attachment metadata.
    #[serde(default)]
    pub max_bytes: Option<u32>,
}

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct CreateDraftArgs {
    /// From address. Typically your iCloud alias, e.g. "you@icloud.com".
    pub from: String,
    /// Recipients. Must contain at least one address.
    pub to: Vec<String>,
    pub subject: String,
    /// Plain text body, or HTML if `html: true`.
    pub body: String,
    #[serde(default)]
    pub cc: Vec<String>,
    #[serde(default)]
    pub bcc: Vec<String>,
    /// Set true if `body` is HTML; a multipart/alternative draft is built.
    #[serde(default)]
    pub html: bool,
}

// ---------- server ----------

#[derive(Clone)]
pub struct IcloudServer {
    state: Arc<ServerState>,
}

struct ServerState {
    /// `None` means the plugin is running but no credentials are loaded yet.
    /// Tools surface a "run /icloud-mcp:setup" error in this state.
    configured: Option<ConfiguredState>,
    stats: Mutex<AuthStats>,
}

struct ConfiguredState {
    config: Arc<Config>,
    caldav: caldav::Client,
    imap: ImapClient,
}

#[derive(Default)]
struct AuthStats {
    last_imap_ok_at: Option<DateTime<Utc>>,
    last_caldav_ok_at: Option<DateTime<Utc>>,
}

const SETUP_HINT: &str = "icloud-mcp is not configured. Run /icloud-mcp:setup to provide an Apple ID and app-specific password.";

/// URL the client should direct the user to in order to complete the
/// elicitation. Points at the plugin's Quick Start section in the public
/// README so users without local clones still see the instructions.
const SETUP_URL: &str =
    "https://github.com/nikolaypavlov/claude-skills/blob/main/icloud-mcp/README.md#quick-start";

/// Build the URL_ELICITATION_REQUIRED error returned from every tool when
/// the server is in unconfigured mode. MCP 2025-06-18 standardizes this
/// shape (`code = -32042`, `data: {url, elicitationId}`) so the client can
/// render a "needs authentication" affordance instead of a generic failure.
fn setup_required_error() -> McpError {
    McpError::url_elicitation_required(
        SETUP_HINT,
        Some(serde_json::json!({
            "url": SETUP_URL,
            "elicitationId": Uuid::new_v4().to_string(),
        })),
    )
}

#[tool_router]
impl IcloudServer {
    /// Build a fully-configured server. Returns Err if either backend
    /// (CalDAV bootstrap or IMAP TLS config) cannot be initialized - those
    /// failures are unrelated to credentials and indicate environment issues.
    pub async fn new(config: Config) -> anyhow::Result<Self> {
        let config = Arc::new(config);
        let caldav = caldav::Client::new(&config)
            .await
            .map_err(|e| anyhow::anyhow!("caldav init: {e}"))?;
        let imap =
            ImapClient::new(config.clone()).map_err(|e| anyhow::anyhow!("imap init: {e}"))?;
        Ok(Self::with_state(Some(ConfiguredState {
            config,
            caldav,
            imap,
        })))
    }

    /// Build an unconfigured server. Tools that need credentials return a
    /// setup-hint error; `auth_status` still works.
    pub fn unconfigured() -> Self {
        Self::with_state(None)
    }

    fn with_state(configured: Option<ConfiguredState>) -> Self {
        Self {
            state: Arc::new(ServerState {
                configured,
                stats: Mutex::new(AuthStats::default()),
            }),
        }
    }

    fn require(&self) -> Result<&ConfiguredState, McpError> {
        self.state
            .configured
            .as_ref()
            .ok_or_else(setup_required_error)
    }

    async fn mark_imap_ok(&self) {
        self.state.stats.lock().await.last_imap_ok_at = Some(Utc::now());
    }

    async fn mark_caldav_ok(&self) {
        self.state.stats.lock().await.last_caldav_ok_at = Some(Utc::now());
    }

    // ---- Calendar (CalDAV) ----

    #[tool(
        description = "List all iCloud calendars. Returns id (href), display_name, and color. Use id with the other calendar_* tools."
    )]
    async fn calendar_list_calendars(&self) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let cals = s
            .caldav
            .list_calendars()
            .await
            .map_err(|e| to_mcp("calendar_list_calendars", e))?;
        self.mark_caldav_ok().await;
        Ok(json_result(&cals))
    }

    #[tool(description = "List VEVENTs in a calendar between start and end (RFC 3339 UTC).")]
    async fn calendar_list_events(
        &self,
        Parameters(args): Parameters<ListEventsArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let start = parse_rfc3339(&args.start, "start")?;
        let end = parse_rfc3339(&args.end, "end")?;
        let events = s
            .caldav
            .list_events(&args.calendar_id, start, end)
            .await
            .map_err(|e| to_mcp("calendar_list_events", e))?;
        self.mark_caldav_ok().await;
        Ok(json_result(&events))
    }

    #[tool(
        description = "Fetch one VEVENT by UID (or .ics href) from a calendar. Returns parsed fields plus raw iCalendar text."
    )]
    async fn calendar_get_event(
        &self,
        Parameters(args): Parameters<GetEventArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let ev = s
            .caldav
            .get_event(&args.calendar_id, &args.uid)
            .await
            .map_err(|e| to_mcp("calendar_get_event", e))?;
        self.mark_caldav_ok().await;
        Ok(json_result(&ev))
    }

    #[tool(
        description = "Search events by case-insensitive substring across SUMMARY and LOCATION. Defaults to the window [30 days ago, 90 days ahead] across all calendars."
    )]
    async fn calendar_search_events(
        &self,
        Parameters(args): Parameters<SearchEventsArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let now = Utc::now();
        let start = match &args.start {
            Some(s) => parse_rfc3339(s, "start")?,
            None => now - Duration::days(30),
        };
        let end = match &args.end {
            Some(s) => parse_rfc3339(s, "end")?,
            None => now + Duration::days(90),
        };
        let events = s
            .caldav
            .search_events(&args.query, start, end, args.calendar_id.as_deref())
            .await
            .map_err(|e| to_mcp("calendar_search_events", e))?;
        self.mark_caldav_ok().await;
        Ok(json_result(&events))
    }

    #[tool(
        description = "Create a new event in a calendar. RFC 3339 UTC times. ORGANIZER is set automatically to your Apple ID."
    )]
    async fn calendar_create_event(
        &self,
        Parameters(args): Parameters<CreateEventArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let start = parse_rfc3339(&args.start, "start")?;
        let end = parse_rfc3339(&args.end, "end")?;
        if end <= start {
            return Err(invalid_params("`end` must be after `start`"));
        }
        let params = caldav::CreateEventParams {
            title: args.title,
            start,
            end,
            description: args.description,
            location: args.location,
            attendees: args.attendees,
            organizer: s.config.apple_id.clone(),
        };
        let summary = s
            .caldav
            .create_event(&args.calendar_id, params)
            .await
            .map_err(|e| to_mcp("calendar_create_event", e))?;
        self.mark_caldav_ok().await;
        Ok(json_result(&summary))
    }

    // ---- Mail (IMAP read + APPEND drafts) ----

    #[tool(
        description = "List all IMAP folders. Each entry has a name and optional special_use label (Drafts, Sent, Trash, Junk, Archive, Flagged, All)."
    )]
    async fn mail_list_folders(&self) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let folders = s
            .imap
            .list_folders()
            .await
            .map_err(|e| to_mcp("mail_list_folders", e))?;
        self.mark_imap_ok().await;
        Ok(json_result(&folders))
    }

    #[tool(
        description = "Search messages in a folder. All filters are AND-combined. Returns up to `limit` newest-first summaries. Use UIDs with mail_get_message."
    )]
    async fn mail_search(
        &self,
        Parameters(args): Parameters<MailSearchArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let since = match &args.since {
            Some(s) => Some(parse_rfc3339(s, "since")?),
            None => None,
        };
        let before = match &args.before {
            Some(s) => Some(parse_rfc3339(s, "before")?),
            None => None,
        };
        let criteria = SearchCriteria {
            from: args.from,
            subject: args.subject,
            text: args.text,
            since,
            before,
            unseen: args.unseen,
        };
        let messages = s
            .imap
            .search(&args.folder, &criteria, args.limit)
            .await
            .map_err(|e| to_mcp("mail_search", e))?;
        self.mark_imap_ok().await;
        Ok(json_result(&messages))
    }

    #[tool(
        description = "Fetch one message by UID from a folder. Returns parsed headers, body (HTML converted to markdown when no plain-text part exists), attachment metadata, and `truncated` + `total_size_bytes` when the body was capped by `max_bytes`."
    )]
    async fn mail_get_message(
        &self,
        Parameters(args): Parameters<MailGetArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let msg = s
            .imap
            .get_message(&args.folder, args.uid, args.max_bytes)
            .await
            .map_err(|e| to_mcp("mail_get_message", e))?;
        self.mark_imap_ok().await;
        Ok(json_result(&msg))
    }

    #[tool(
        description = "Create a DRAFT email (does NOT send). The message is APPENDed to the Drafts IMAP folder with the \\Draft flag; the user reviews and sends it manually in iCloud Mail. Set html=true if `body` is HTML."
    )]
    async fn mail_create_draft(
        &self,
        Parameters(args): Parameters<CreateDraftArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        if args.to.is_empty() {
            return Err(invalid_params("`to` must contain at least one address"));
        }
        let params = DraftParams {
            from: args.from,
            to: args.to,
            cc: args.cc,
            bcc: args.bcc,
            subject: args.subject,
            body: args.body,
            html: args.html,
        };
        let res = s
            .imap
            .create_draft(&params)
            .await
            .map_err(|e| to_mcp("mail_create_draft", e))?;
        self.mark_imap_ok().await;
        Ok(json_result(&res))
    }

    // ---- Diagnostics ----

    #[tool(
        description = "Diagnose plugin auth state. Returns whether credentials are loaded, which source (env vs Keychain), and the timestamp of the last successful IMAP / CalDAV call. Call this when other tools fail to determine whether to run /icloud-mcp:setup."
    )]
    async fn auth_status(&self) -> Result<CallToolResult, McpError> {
        let stats = self.state.stats.lock().await;
        let configured = self.state.configured.as_ref();
        let setup_hint = if configured.is_some() {
            "Credentials are loaded. If tools fail, the password may have been revoked; mint a new one and re-run /icloud-mcp:setup.".to_string()
        } else {
            SETUP_HINT.to_string()
        };
        let body = serde_json::json!({
            "apple_id": configured.map(|c| c.config.apple_id.clone()),
            "credential_source": configured.map(|c| c.config.source),
            "binary_version": env!("CARGO_PKG_VERSION"),
            "last_imap_ok_at": stats.last_imap_ok_at.map(|t| t.to_rfc3339()),
            "last_caldav_ok_at": stats.last_caldav_ok_at.map(|t| t.to_rfc3339()),
            "setup_hint": setup_hint,
            "setup_url": SETUP_URL,
        });
        Ok(json_result(&body))
    }
}

#[tool_handler]
impl ServerHandler for IcloudServer {
    fn get_info(&self) -> ServerInfo {
        let instructions = if self.state.configured.is_some() {
            "Local MCP server for Apple iCloud Calendar (CalDAV) and Mail (IMAP). \
             Read + create-only: events can be created, mail can only be saved as drafts \
             - there is no SMTP transport, the user reviews and sends manually in iCloud Mail. \
             All datetimes are RFC 3339 UTC. \
             Workflow: 1) `calendar_list_calendars` / `mail_list_folders` to discover ids; \
             2) list/search/get with those ids; 3) `calendar_create_event` or \
             `mail_create_draft` for write operations."
                .to_string()
        } else {
            format!(
                "{SETUP_HINT} Until then, the only working tool is `auth_status` (diagnostics)."
            )
        };
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build())
            .with_protocol_version(ProtocolVersion::V_2025_06_18)
            .with_instructions(instructions)
    }
}

// ---------- helpers ----------

fn parse_rfc3339(s: &str, field: &str) -> Result<DateTime<Utc>, McpError> {
    DateTime::parse_from_rfc3339(s)
        .map(|dt| dt.with_timezone(&Utc))
        .map_err(|e| invalid_params(format!("`{field}` is not valid RFC 3339: {e}")))
}

fn json_result<T: serde::Serialize>(value: &T) -> CallToolResult {
    let text = serde_json::to_string_pretty(value)
        .unwrap_or_else(|e| format!("{{\"error\":\"serialization failed: {e}\"}}"));
    CallToolResult::success(vec![Content::text(text)])
}

// ---------- entry point ----------

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // rustls 0.23 requires an explicit crypto provider to be installed before any TLS use.
    let _ = rustls::crypto::ring::default_provider().install_default();

    let filter_spec = std::env::var("ICLOUD_MCP_LOG")
        .or_else(|_| std::env::var("RUST_LOG"))
        .unwrap_or_else(|_| "icloud_mcp=info".to_string());
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::new(filter_spec))
        .with_writer(std::io::stderr)
        .with_ansi(false)
        .init();

    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--probe") {
        return run_probe().await;
    }

    tracing::info!(version = env!("CARGO_PKG_VERSION"), "icloud-mcp starting");

    let server = match Config::try_load() {
        Some(config) => {
            tracing::info!(source = ?config.source, apple_id = %config.apple_id, "config loaded");
            IcloudServer::new(config).await?
        }
        None => {
            tracing::warn!(
                "no credentials available (env vars APPLE_ID/APPLE_APP_PASSWORD missing \
                 and no Keychain entry); starting in unconfigured mode - run /icloud-mcp:setup"
            );
            IcloudServer::unconfigured()
        }
    };

    let service = server
        .serve(stdio())
        .await
        .inspect_err(|e| tracing::error!("serve error: {e:?}"))?;
    service.waiting().await?;
    Ok(())
}

/// `icloud-mcp --probe`: load credentials, attempt one IMAP login and one
/// CalDAV bootstrap, write a JSON diagnostic to stdout, exit.
///
/// Used by `/icloud-mcp:setup` to verify credentials immediately after the
/// user pastes the app-specific password, and by humans for manual debugging.
async fn run_probe() -> anyhow::Result<()> {
    let config = match Config::load() {
        Ok(c) => c,
        Err(e) => {
            let out = serde_json::json!({
                "ok": false,
                "stage": "config",
                "error": format!("{e:#}"),
            });
            println!("{}", serde_json::to_string_pretty(&out)?);
            return Ok(());
        }
    };

    let apple_id = config.apple_id.clone();
    let source = config.source;

    // IMAP login + folder count.
    let imap_result: Result<usize, String> = match ImapClient::new(Arc::new(config.clone())) {
        Ok(c) => match c.list_folders().await {
            Ok(fs) => Ok(fs.len()),
            Err(e) => Err(e.to_string()),
        },
        Err(e) => Err(e.to_string()),
    };

    // CalDAV bootstrap + calendar count.
    let caldav_result: Result<usize, String> = match caldav::Client::new(&config).await {
        Ok(c) => match c.list_calendars().await {
            Ok(cs) => Ok(cs.len()),
            Err(e) => Err(e.to_string()),
        },
        Err(e) => Err(e.to_string()),
    };

    let imap_ok = imap_result.is_ok();
    let caldav_ok = caldav_result.is_ok();

    let out = serde_json::json!({
        "ok": imap_ok && caldav_ok,
        "apple_id": apple_id,
        "credential_source": source,
        "imap": match &imap_result {
            Ok(n) => serde_json::json!({ "ok": true, "folders": n }),
            Err(e) => serde_json::json!({ "ok": false, "error": e }),
        },
        "caldav": match &caldav_result {
            Ok(n) => serde_json::json!({ "ok": true, "calendars": n }),
            Err(e) => serde_json::json!({ "ok": false, "error": e }),
        },
    });
    println!("{}", serde_json::to_string_pretty(&out)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_rfc3339_accepts_utc_z() {
        let dt = parse_rfc3339("2026-05-14T09:30:00Z", "start").unwrap();
        assert_eq!(dt.to_rfc3339(), "2026-05-14T09:30:00+00:00");
    }

    #[test]
    fn parse_rfc3339_accepts_offset() {
        let dt = parse_rfc3339("2026-05-14T11:30:00+02:00", "start").unwrap();
        assert_eq!(dt.to_rfc3339(), "2026-05-14T09:30:00+00:00");
    }

    #[test]
    fn parse_rfc3339_rejects_garbage() {
        let err = parse_rfc3339("yesterday", "end").unwrap_err();
        let msg = format!("{err:?}");
        assert!(msg.contains("end"));
    }

    #[test]
    fn json_result_wraps_struct_as_text_content() {
        #[derive(serde::Serialize)]
        struct X {
            a: i32,
            b: String,
        }
        let r = json_result(&X {
            a: 1,
            b: "two".into(),
        });
        // CallToolResult holds Content::Text { text: <serialized JSON> }. The inner
        // JSON gets re-escaped inside the outer text field, so verify by unwrapping.
        let rendered = serde_json::to_string(&r).unwrap();
        let v: serde_json::Value = serde_json::from_str(&rendered).unwrap();
        let text = v["content"][0]["text"].as_str().expect("text content");
        let inner: serde_json::Value = serde_json::from_str(text).unwrap();
        assert_eq!(inner["a"], 1);
        assert_eq!(inner["b"], "two");
    }

    #[test]
    fn default_limit_is_25() {
        assert_eq!(default_limit(), 25);
    }

    #[tokio::test]
    async fn unconfigured_server_returns_url_elicitation() {
        use rmcp::model::ErrorCode;
        let s = IcloudServer::unconfigured();
        let err = s.calendar_list_calendars().await.unwrap_err();
        assert_eq!(
            err.code,
            ErrorCode::URL_ELICITATION_REQUIRED,
            "expected -32042, got {err:?}"
        );
        assert!(err.message.contains("/icloud-mcp:setup"), "msg: {err:?}");
        let data = err
            .data
            .expect("error data must include url + elicitationId");
        assert_eq!(data["url"], SETUP_URL);
        assert!(data["elicitationId"].is_string());
    }

    #[tokio::test]
    async fn unconfigured_auth_status_reports_no_credentials() {
        let s = IcloudServer::unconfigured();
        let r = s.auth_status().await.expect("auth_status should not error");
        let rendered = serde_json::to_string(&r).unwrap();
        let v: serde_json::Value = serde_json::from_str(&rendered).unwrap();
        let text = v["content"][0]["text"].as_str().expect("text content");
        let inner: serde_json::Value = serde_json::from_str(text).unwrap();
        assert!(inner["apple_id"].is_null());
        assert!(inner["credential_source"].is_null());
        assert!(inner["setup_hint"]
            .as_str()
            .unwrap()
            .contains("/icloud-mcp:setup"));
    }
}
