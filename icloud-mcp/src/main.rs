mod caldav;
mod config;
mod error;
mod imap_client;

use std::sync::Arc;

use chrono::{DateTime, Duration, Utc};
use rmcp::{
    ErrorData as McpError, ServerHandler, ServiceExt,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{
        CallToolResult, Content, Implementation, ProtocolVersion, ServerCapabilities, ServerInfo,
    },
    schemars, tool, tool_handler, tool_router,
    transport::stdio,
};
use tracing_subscriber::EnvFilter;

use crate::config::Config;
use crate::error::{invalid_params, to_mcp};
use crate::imap_client::{DraftParams, ImapClient, SearchCriteria};

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
    tool_router: ToolRouter<Self>,
}

struct ServerState {
    config: Arc<Config>,
    caldav: caldav::Client,
    imap: ImapClient,
}

#[tool_router]
impl IcloudServer {
    pub async fn new(config: Config) -> anyhow::Result<Self> {
        let config = Arc::new(config);
        let caldav = caldav::Client::new(&config).await?;
        let imap = ImapClient::new(config.clone())?;
        let state = Arc::new(ServerState {
            config,
            caldav,
            imap,
        });
        Ok(Self {
            state,
            tool_router: Self::tool_router(),
        })
    }

    // ---- Calendar (CalDAV) ----

    #[tool(
        description = "List all iCloud calendars. Returns id (href), display_name, and color. Use id with the other calendar_* tools."
    )]
    async fn calendar_list_calendars(&self) -> Result<CallToolResult, McpError> {
        let cals = self
            .state
            .caldav
            .list_calendars()
            .await
            .map_err(|e| to_mcp("calendar_list_calendars", e))?;
        Ok(json_result(&cals))
    }

    #[tool(
        description = "List VEVENTs in a calendar between start and end (RFC 3339 UTC)."
    )]
    async fn calendar_list_events(
        &self,
        Parameters(args): Parameters<ListEventsArgs>,
    ) -> Result<CallToolResult, McpError> {
        let start = parse_rfc3339(&args.start, "start")?;
        let end = parse_rfc3339(&args.end, "end")?;
        let events = self
            .state
            .caldav
            .list_events(&args.calendar_id, start, end)
            .await
            .map_err(|e| to_mcp("calendar_list_events", e))?;
        Ok(json_result(&events))
    }

    #[tool(
        description = "Fetch one VEVENT by UID (or .ics href) from a calendar. Returns parsed fields plus raw iCalendar text."
    )]
    async fn calendar_get_event(
        &self,
        Parameters(args): Parameters<GetEventArgs>,
    ) -> Result<CallToolResult, McpError> {
        let ev = self
            .state
            .caldav
            .get_event(&args.calendar_id, &args.uid)
            .await
            .map_err(|e| to_mcp("calendar_get_event", e))?;
        Ok(json_result(&ev))
    }

    #[tool(
        description = "Search events by case-insensitive substring across SUMMARY and LOCATION. Defaults to the window [30 days ago, 90 days ahead] across all calendars."
    )]
    async fn calendar_search_events(
        &self,
        Parameters(args): Parameters<SearchEventsArgs>,
    ) -> Result<CallToolResult, McpError> {
        let now = Utc::now();
        let start = match &args.start {
            Some(s) => parse_rfc3339(s, "start")?,
            None => now - Duration::days(30),
        };
        let end = match &args.end {
            Some(s) => parse_rfc3339(s, "end")?,
            None => now + Duration::days(90),
        };
        let events = self
            .state
            .caldav
            .search_events(&args.query, start, end, args.calendar_id.as_deref())
            .await
            .map_err(|e| to_mcp("calendar_search_events", e))?;
        Ok(json_result(&events))
    }

    #[tool(
        description = "Create a new event in a calendar. RFC 3339 UTC times. ORGANIZER is set automatically to your Apple ID."
    )]
    async fn calendar_create_event(
        &self,
        Parameters(args): Parameters<CreateEventArgs>,
    ) -> Result<CallToolResult, McpError> {
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
            organizer: self.state.config.apple_id.clone(),
        };
        let summary = self
            .state
            .caldav
            .create_event(&args.calendar_id, params)
            .await
            .map_err(|e| to_mcp("calendar_create_event", e))?;
        Ok(json_result(&summary))
    }

    // ---- Mail (IMAP read + APPEND drafts) ----

    #[tool(
        description = "List all IMAP folders. Each entry has a name and optional special_use label (Drafts, Sent, Trash, Junk, Archive, Flagged, All)."
    )]
    async fn mail_list_folders(&self) -> Result<CallToolResult, McpError> {
        let folders = self
            .state
            .imap
            .list_folders()
            .await
            .map_err(|e| to_mcp("mail_list_folders", e))?;
        Ok(json_result(&folders))
    }

    #[tool(
        description = "Search messages in a folder. All filters are AND-combined. Returns up to `limit` newest-first summaries. Use UIDs with mail_get_message."
    )]
    async fn mail_search(
        &self,
        Parameters(args): Parameters<MailSearchArgs>,
    ) -> Result<CallToolResult, McpError> {
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
        let messages = self
            .state
            .imap
            .search(&args.folder, &criteria, args.limit)
            .await
            .map_err(|e| to_mcp("mail_search", e))?;
        Ok(json_result(&messages))
    }

    #[tool(
        description = "Fetch one message by UID from a folder. Returns parsed headers, body (HTML converted to markdown when no plain-text part exists), and attachment filenames."
    )]
    async fn mail_get_message(
        &self,
        Parameters(args): Parameters<MailGetArgs>,
    ) -> Result<CallToolResult, McpError> {
        let msg = self
            .state
            .imap
            .get_message(&args.folder, args.uid)
            .await
            .map_err(|e| to_mcp("mail_get_message", e))?;
        Ok(json_result(&msg))
    }

    #[tool(
        description = "Create a DRAFT email (does NOT send). The message is APPENDed to the Drafts IMAP folder with the \\Draft flag; the user reviews and sends it manually in iCloud Mail. Set html=true if `body` is HTML."
    )]
    async fn mail_create_draft(
        &self,
        Parameters(args): Parameters<CreateDraftArgs>,
    ) -> Result<CallToolResult, McpError> {
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
        let res = self
            .state
            .imap
            .create_draft(&params)
            .await
            .map_err(|e| to_mcp("mail_create_draft", e))?;
        Ok(json_result(&res))
    }
}

#[tool_handler]
impl ServerHandler for IcloudServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation::from_build_env(),
            instructions: Some(
                "Local MCP server for Apple iCloud Calendar (CalDAV) and Mail (IMAP). \
                 Read + create-only: events can be created, mail can only be saved as drafts \
                 - there is no SMTP transport, the user reviews and sends manually in iCloud Mail. \
                 All datetimes are RFC 3339 UTC. \
                 Workflow: 1) `calendar_list_calendars` / `mail_list_folders` to discover ids; \
                 2) list/search/get with those ids; 3) `calendar_create_event` or \
                 `mail_create_draft` for write operations."
                    .to_string(),
            ),
        }
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

    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("icloud_mcp=info")),
        )
        .with_writer(std::io::stderr)
        .with_ansi(false)
        .init();

    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        "icloud-mcp starting"
    );

    let config = Config::load()?;
    let server = IcloudServer::new(config).await?;

    let service = server
        .serve(stdio())
        .await
        .inspect_err(|e| tracing::error!("serve error: {e:?}"))?;
    service.waiting().await?;
    Ok(())
}
