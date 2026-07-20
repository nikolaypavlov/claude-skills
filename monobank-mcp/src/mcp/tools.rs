//! MCP tool surface for monobank-mcp.
//!
//! Three tools (per design v2.1 §5.5):
//!   - `ensure_synced`       - inline incremental sync with wall-clock budget
//!   - `get_sync_status`     - report cursor + gap per account
//!   - `list_mono_accounts`  - diagnostic listing of accounts visible to mono
//!
//! Tools surface a `URL_ELICITATION_REQUIRED` error pointing at
//! `/monobank-mcp:setup` when the binary is started without a token. This
//! mirrors the icloud-mcp pattern: every tool except diagnostics fails fast
//! and the LLM gets explicit guidance to direct the user to the setup
//! command instead of asking for a token in chat.

use std::sync::Arc;
use std::time::{Duration, Instant};

use rmcp::{
    handler::server::wrapper::Parameters,
    model::{CallToolResult, Content, ProtocolVersion, ServerCapabilities, ServerInfo},
    schemars, tool, tool_handler, tool_router, ErrorData as McpError, ServerHandler,
};
use serde_json::json;

use crate::api::MonobankApi;
use crate::config::Config;
use crate::error::to_mcp;
use crate::store::Store;
use crate::sync::SyncEngine;
use crate::util::ratelimit::RateLimiter;
use crate::util::time::now_unix;

// `elicitationId` is opaque to the protocol; we just need a unique tag per
// error event. Avoids pulling in `uuid` as a dependency.
fn elicitation_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(1);
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("mono-{ts:032x}-{n:08x}")
}

const SETUP_HINT: &str =
    "monobank-mcp is not configured. Run /monobank-mcp:setup to provide a personal API token.";

const SETUP_PROMPT: &str = "\
monobank-mcp has no API token loaded. Do NOT ask the user to paste a token in chat - tokens \
should not appear in conversation history. Instead, tell the user to run the slash command \
`/monobank-mcp:setup` in this Claude Code session. That command walks them through generating \
a token at https://api.monobank.ua/, stores it in macOS Keychain (or instructs them to set \
the MONOBANK_TOKEN env var on Linux), and verifies the connection by listing the user's \
accounts. Until the wizard completes only diagnostics work; every other monobank-mcp tool \
returns this same error.";

const SETUP_URL: &str =
    "https://github.com/nikolaypavlov/claude-skills/blob/main/monobank-mcp/README.md#quick-start";

fn setup_required_error() -> McpError {
    McpError::url_elicitation_required(
        SETUP_PROMPT,
        Some(json!({
            "url": SETUP_URL,
            "elicitationId": elicitation_id(),
            "nextAction": {
                "type": "slash_command",
                "command": "/monobank-mcp:setup",
                "description": "Interactive wizard that captures a Monobank Personal API token.",
            },
        })),
    )
}

// ---------- Tool argument types ----------

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct EnsureSyncedArgs {
    /// Max wall-clock seconds this call may consume. Defaults to the
    /// configured `ensure_synced_default_budget` (typically 90s) which is
    /// safely below the standard Claude Desktop tool timeout.
    #[serde(default)]
    pub max_wait_seconds: Option<u64>,
    /// Limit sync to a single account id. If omitted, all accounts in
    /// `mono_accounts` are processed.
    #[serde(default)]
    pub account_id: Option<String>,
}

#[derive(serde::Deserialize, schemars::JsonSchema, Debug)]
pub struct GetSyncStatusArgs {
    #[serde(default)]
    pub account_id: Option<String>,
}

// ---------- Server ----------

#[derive(Clone)]
pub struct MonobankServer {
    state: Arc<ServerState>,
}

struct ServerState {
    configured: Option<ConfiguredState>,
}

pub(crate) struct ConfiguredState {
    pub config: Arc<Config>,
    pub api: MonobankApi,
    pub store: Store,
    pub limiter: RateLimiter,
}

#[tool_router]
impl MonobankServer {
    pub async fn new(config: Config, store: Store) -> anyhow::Result<Self> {
        let api = MonobankApi::new(config.api_base.clone(), config.token.clone())
            .map_err(|e| anyhow::anyhow!("api init: {e}"))?;
        let limiter = RateLimiter::new(Duration::from_secs(config.api_min_interval_seconds));
        let config = Arc::new(config);
        Ok(Self {
            state: Arc::new(ServerState {
                configured: Some(ConfiguredState {
                    config,
                    api,
                    store,
                    limiter,
                }),
            }),
        })
    }

    pub fn unconfigured() -> Self {
        Self {
            state: Arc::new(ServerState { configured: None }),
        }
    }

    fn require(&self) -> Result<&ConfiguredState, McpError> {
        self.state
            .configured
            .as_ref()
            .ok_or_else(setup_required_error)
    }

    #[tool(
        description = "Run an inline incremental sync of Monobank accounts. Bounded by `max_wait_seconds` so the tool returns before Claude's timeout; partial=true and remaining_chunks>0 signal that more chunks are pending and the user should re-invoke or run `monobank-mcp sync` from the CLI."
    )]
    async fn ensure_synced(
        &self,
        Parameters(args): Parameters<EnsureSyncedArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let budget = args
            .max_wait_seconds
            .unwrap_or(s.config.ensure_synced_default_budget);
        let deadline = Instant::now() + Duration::from_secs(budget);
        let interval = Duration::from_secs(s.config.api_min_interval_seconds);

        let targets = pick_accounts(&s.store, args.account_id.as_deref())
            .await
            .map_err(|e| to_mcp("ensure_synced", e))?;

        let engine = SyncEngine::for_mcp(
            s.api.clone(),
            s.store.clone(),
            s.limiter.clone(),
            interval,
            s.config.sync_freshness_skip_seconds,
            deadline,
        );
        let outcome = engine
            .run(&targets)
            .await
            .map_err(|e| McpError::internal_error(format!("ensure_synced: {e}"), None))?;
        let body = json!({
            "synced": !outcome.partial(),
            "partial": outcome.partial(),
            "caught_up": outcome.caught_up,
            "skipped": outcome.skipped_all,
            "rows_added": outcome.rows_added,
            "remaining_chunks": outcome.remaining_chunks,
            "per_account": outcome.per_account,
        });
        Ok(json_result(&body))
    }

    #[tool(
        description = "Report the sync cursor and gap (seconds to now) for each known account. Returns an empty array when no backfill has run yet."
    )]
    async fn get_sync_status(
        &self,
        Parameters(args): Parameters<GetSyncStatusArgs>,
    ) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let now = now_unix();
        let rows = match args.account_id {
            Some(id) => s
                .store
                .get_sync_state(&id)
                .await
                .map_err(|e| McpError::internal_error(format!("get_sync_status: {e}"), None))?
                .into_iter()
                .collect(),
            None => s
                .store
                .list_sync_state()
                .await
                .map_err(|e| McpError::internal_error(format!("get_sync_status: {e}"), None))?,
        };
        let body: Vec<_> = rows
            .into_iter()
            .map(|r| {
                json!({
                    "bank": "mono",
                    "account_id": r.account_id,
                    "last_completed_ts": r.last_completed_ts,
                    "last_sync_at": r.last_sync_at,
                    "gap_seconds": (now - r.last_completed_ts).max(0),
                })
            })
            .collect();
        Ok(json_result(&body))
    }

    #[tool(
        description = "List Mono accounts visible locally. Use this for setup verification (\"can mono see my card?\"). For full cross-bank account listing use the personal-finance plugin's list_accounts tool."
    )]
    async fn list_mono_accounts(&self) -> Result<CallToolResult, McpError> {
        let s = self.require()?;
        let rows = s
            .store
            .list_accounts()
            .await
            .map_err(|e| McpError::internal_error(format!("list_mono_accounts: {e}"), None))?;
        Ok(json_result(&rows))
    }
}

#[tool_handler]
impl ServerHandler for MonobankServer {
    fn get_info(&self) -> ServerInfo {
        let instructions = if self.state.configured.is_some() {
            "Local MCP server for Monobank Personal API. Slim ingest: pulls statements into the \
             shared SQLite store (`~/finances/data.db`). Tools: ensure_synced (inline incremental \
             sync), get_sync_status (cursor/gap per account), list_mono_accounts (diagnostic). \
             For query/report/categorisation, use the personal-finance plugin."
                .to_string()
        } else {
            format!("{SETUP_HINT} Until then no tools succeed - run /monobank-mcp:setup.")
        };
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build())
            .with_protocol_version(ProtocolVersion::V_2025_06_18)
            .with_instructions(instructions)
    }
}

async fn pick_accounts(
    store: &Store,
    explicit: Option<&str>,
) -> Result<Vec<String>, crate::error::DomainError> {
    if let Some(id) = explicit {
        return Ok(vec![id.to_string()]);
    }
    let rows = store
        .list_accounts()
        .await
        .map_err(|e| crate::error::DomainError::from_err("list_accounts", e))?;
    Ok(rows.into_iter().map(|r| r.account_id).collect())
}

pub(crate) fn json_result<T: serde::Serialize>(value: &T) -> CallToolResult {
    let text = serde_json::to_string_pretty(value)
        .unwrap_or_else(|e| format!("{{\"error\":\"serialization failed: {e}\"}}"));
    CallToolResult::success(vec![Content::text(text)])
}

#[cfg(test)]
mod tests {
    use super::*;
    use rmcp::model::ErrorCode;

    #[tokio::test]
    async fn unconfigured_ensure_synced_returns_url_elicitation() {
        let s = MonobankServer::unconfigured();
        let err = s
            .ensure_synced(Parameters(EnsureSyncedArgs {
                max_wait_seconds: None,
                account_id: None,
            }))
            .await
            .unwrap_err();
        assert_eq!(err.code, ErrorCode::URL_ELICITATION_REQUIRED);
        assert!(err.message.contains("/monobank-mcp:setup"));
    }
}
