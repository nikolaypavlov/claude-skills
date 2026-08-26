//! MCP tool surface for monobank-mcp.
//!
//! Three tools (per design v2.1 §5.5):
//!   - `ensure_synced`       - inline incremental sync with wall-clock budget
//!   - `get_sync_status`     - cursor + balance reconciliation per account
//!   - `list_mono_accounts`  - diagnostic listing of accounts visible to mono
//!
//! Tool descriptions are the only documentation the model gets at call time,
//! so they carry the two claims a caller must not get wrong: `rows_added: 0`
//! is not evidence of anything, and only `caught_up: true` licenses "the DB
//! is current". Keep them in sync with `sync.rs` doc comments and README.md.
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
        description = "Run an inline incremental sync of Monobank accounts, bounded by `max_wait_seconds` so the tool returns before Claude's timeout. Trust ONLY `caught_up: true` as \"the local DB covers everything up to now\". `rows_added: 0` proves nothing on its own - an account with `remaining_chunks > 0` (status `unattempted` / `partial`) was never fetched, or only partly fetched, and its window is unchecked; re-invoke the tool or run `monobank-mcp sync` from the CLI until `caught_up` is true. Accounts are served stalest-first, so repeated calls reach every account. `estimated_catch_up_seconds` is how long the remaining work needs at the API rate limit - when it exceeds the budget you can afford, run `monobank-mcp sync` in the background instead of re-invoking this tool repeatedly. Separately, `suspected_missing_rows: true` means an account's stored balance disagrees with its newest stored transaction: rows are missing inside an already-synced window and only `monobank-mcp backfill --from <date> --account <id>` recovers them."
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
        let suspect = outcome.accounts_with_suspected_gaps();
        let body = json!({
            "synced": !outcome.partial(),
            "partial": outcome.partial(),
            "caught_up": outcome.caught_up,
            "skipped": outcome.skipped_all,
            "rows_added": outcome.rows_added,
            "remaining_chunks": outcome.remaining_chunks,
            // What a follow-up costs, so a caller weighing "re-invoke or go
            // to the CLI" does not have to know the rate limit to decide.
            "estimated_catch_up_seconds": outcome.estimated_catch_up_seconds,
            // Hoisted out of `balance_checks` so a gap cannot be missed by a
            // caller that only skims the top level of the response.
            "suspected_missing_rows": !suspect.is_empty(),
            "accounts_with_suspected_gaps": suspect,
            "per_account": outcome.per_account,
            "balance_checks": outcome.balance_checks,
        });
        Ok(json_result(&body))
    }

    #[tool(
        description = "Report the sync cursor per account plus a balance reconciliation. `gap_seconds` is cursor lag and is diagnostic only - it does not mean the data up to now has been checked. `balance_matches_last_tx` compares the account balance from client-info against the running balance on the newest stored transaction: `false` proves rows are missing; `null` means not comparable (no balance snapshot, or the snapshot predates the newest row - run `monobank-mcp accounts` to refresh it) and must never be read as \"fine\". Returns an empty array when no backfill has run yet."
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
        let checks = s
            .store
            .balance_checks()
            .await
            .map_err(|e| McpError::internal_error(format!("get_sync_status: {e}"), None))?;
        let body: Vec<_> = rows
            .into_iter()
            .map(|r| {
                let check = checks.iter().find(|c| c.account_id == r.account_id);
                json!({
                    "bank": "mono",
                    "account_id": r.account_id,
                    "last_completed_ts": r.last_completed_ts,
                    "last_sync_at": r.last_sync_at,
                    "gap_seconds": (now - r.last_completed_ts).max(0),
                    "balance_matches_last_tx": check.and_then(|c| c.balance_matches_last_tx),
                    "suspected_missing_rows": check.is_some_and(|c| c.suspected_missing_rows),
                    "balance_check": check,
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

/// Accounts to sync, stalest cursor first.
///
/// The order is the anti-starvation mechanism. `ensure_synced` affords about
/// `max_wait_seconds / api_min_interval_seconds` API calls - two with the
/// shipped defaults - so with a fixed `ORDER BY account_id` the same two
/// accounts were served on every invocation and the tail was unreachable no
/// matter how many times the caller re-invoked. Fetching an account pushes
/// its cursor to ~now and sends it to the back of the queue, so successive
/// budget-limited calls rotate through all of them.
///
/// An explicit `account_id` bypasses the ordering entirely - the caller has
/// already chosen the target.
async fn pick_accounts(
    store: &Store,
    explicit: Option<&str>,
) -> Result<Vec<String>, crate::error::DomainError> {
    if let Some(id) = explicit {
        return Ok(vec![id.to_string()]);
    }
    store
        .list_account_ids_by_staleness()
        .await
        .map_err(|e| crate::error::DomainError::from_err("list_accounts", e))
}

pub(crate) fn json_result<T: serde::Serialize>(value: &T) -> CallToolResult {
    let text = serde_json::to_string_pretty(value)
        .unwrap_or_else(|e| format!("{{\"error\":\"serialization failed: {e}\"}}"));
    CallToolResult::success(vec![Content::text(text)])
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::MonoAccount;
    use rmcp::model::ErrorCode;

    async fn acc(store: &Store, id: &str) {
        store
            .upsert_account(&MonoAccount {
                id: id.into(),
                iban: None,
                r#type: Some("black".into()),
                currency_code: 980,
                masked_pan: None,
                balance: None,
                credit_limit: None,
                label: None,
            })
            .await
            .unwrap();
    }

    /// `pick_accounts` is what feeds the budget-limited loop, so the
    /// anti-starvation ordering has to hold here and not only in the store.
    /// Under the old `ORDER BY account_id` the busiest card sorted last and
    /// a 90s budget never reached it.
    #[tokio::test]
    async fn pick_accounts_orders_stalest_cursor_first() {
        let store = Store::open_in_memory().unwrap();
        for id in ["aaa_first_by_id", "zzz_last_by_id"] {
            acc(&store, id).await;
        }
        store
            .seed_sync_state("aaa_first_by_id", 9_000)
            .await
            .unwrap();
        store
            .seed_sync_state("zzz_last_by_id", 1_000)
            .await
            .unwrap();

        let picked = pick_accounts(&store, None).await.unwrap();
        assert_eq!(picked, vec!["zzz_last_by_id", "aaa_first_by_id"]);
    }

    /// An explicit account id bypasses the ordering entirely.
    #[tokio::test]
    async fn pick_accounts_honours_explicit_account() {
        let store = Store::open_in_memory().unwrap();
        acc(&store, "aaa_first_by_id").await;
        acc(&store, "zzz_last_by_id").await;
        let picked = pick_accounts(&store, Some("aaa_first_by_id"))
            .await
            .unwrap();
        assert_eq!(picked, vec!["aaa_first_by_id"]);
    }

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
