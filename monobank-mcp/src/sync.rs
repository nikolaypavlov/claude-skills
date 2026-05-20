//! Sync engine - shared between the CLI (`monobank-mcp sync`) and the MCP
//! tool (`ensure_synced`). The only difference is the wall-clock budget: the
//! MCP call passes `max_wait_seconds` so it can return a `partial` result
//! before Claude's tool timeout, while the CLI passes `None` and pulls
//! through to completion.
//!
//! Per-chunk invariants (enforced in `Store::insert_statement_chunk`):
//!   - INSERTs and the `last_completed_ts` UPSERT are atomic.
//!   - The cursor uses MAX() so a retry of an earlier window cannot rewind it.
//!   - INSERT OR IGNORE means re-pulling the same window is a no-op.
//!
//! Time budget:
//!   ```text
//!   for each chunk:
//!     if now() + interval > deadline: stop, mark remaining_chunks
//!     else: rate_limit.wait(); api.statement(...); store.insert_chunk(...)
//!   ```
//!
//! Rate limit retries: a transient `RateLimited` from the API triggers an
//! extra 90s sleep (above the normal 61s interval) and one retry of the
//! same window. After three consecutive failures we surface the error.

use std::time::{Duration, Instant};

use anyhow::Result;
use tracing::{debug, info, warn};

use crate::api::MonobankApi;
use crate::error::DomainError;
use crate::store::Store;
use crate::types::RunSource;
use crate::util::ratelimit::RateLimiter;
use crate::util::time::{chunk_31d, now_unix};

#[derive(Debug, Clone, serde::Serialize)]
pub struct AccountSyncOutcome {
    pub account_id: String,
    pub rows_added: u64,
    pub rows_skipped: u64,
    pub last_completed_ts: i64,
    pub remaining_chunks: u32,
    /// If a chunk failed we record it here and skip the remaining chunks of
    /// that account; the caller decides whether to fail the whole run.
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct SyncOutcome {
    pub per_account: Vec<AccountSyncOutcome>,
    pub rows_added: u64,
    pub remaining_chunks: u32,
    /// True only when there was nothing to do for any account.
    pub skipped_all: bool,
}

impl SyncOutcome {
    pub fn partial(&self) -> bool {
        self.remaining_chunks > 0
    }
}

#[derive(Clone)]
pub struct SyncEngine {
    pub api: MonobankApi,
    pub store: Store,
    pub limiter: RateLimiter,
    /// `None` means CLI-style: no deadline.
    pub deadline: Option<Instant>,
    /// Per-API call interval (the limiter enforces it; we use this for
    /// budgeting "is there time for one more call?").
    pub interval: Duration,
    /// Skip sync when `now - last_sync_at < freshness_skip_seconds`.
    pub freshness_skip_seconds: i64,
    pub source: RunSource,
}

impl SyncEngine {
    /// Process the given account ids in order. Stops cleanly at the deadline.
    pub async fn run(&self, account_ids: &[String]) -> Result<SyncOutcome> {
        let mut out = SyncOutcome {
            skipped_all: !account_ids.is_empty(),
            ..SyncOutcome::default()
        };
        let now = now_unix();

        for acc in account_ids {
            let state = self.store.get_sync_state(acc).await?;
            let last_completed_ts = match &state {
                Some(s) => s.last_completed_ts,
                None => {
                    out.per_account.push(AccountSyncOutcome {
                        account_id: acc.clone(),
                        rows_added: 0,
                        rows_skipped: 0,
                        last_completed_ts: 0,
                        remaining_chunks: 0,
                        error: Some("no backfill yet, run `monobank-mcp backfill` first".into()),
                    });
                    continue;
                }
            };

            // Freshness skip: only meaningful for incremental sync, not for
            // explicit backfill. Backfill ignores this guard by construction
            // because it overrides `last_completed_ts` upstream.
            if let Some(state) = &state {
                let age = now - state.last_sync_at;
                if age < self.freshness_skip_seconds && last_completed_ts >= now - 5 {
                    debug!(account = acc, age_s = age, "freshness skip");
                    out.per_account.push(AccountSyncOutcome {
                        account_id: acc.clone(),
                        rows_added: 0,
                        rows_skipped: 0,
                        last_completed_ts,
                        remaining_chunks: 0,
                        error: None,
                    });
                    continue;
                }
            }

            let chunks = chunk_31d(last_completed_ts, now);
            if chunks.is_empty() {
                out.per_account.push(AccountSyncOutcome {
                    account_id: acc.clone(),
                    rows_added: 0,
                    rows_skipped: 0,
                    last_completed_ts,
                    remaining_chunks: 0,
                    error: None,
                });
                continue;
            }

            out.skipped_all = false;
            let run_id = self.store.start_import_run(self.source).await?;
            let mut acc_added: u64 = 0;
            let mut acc_skipped: u64 = 0;
            let mut last_done_ts = last_completed_ts;
            let mut remaining: u32 = 0;
            let mut error: Option<String> = None;

            for (i, (from, to)) in chunks.iter().enumerate() {
                if self.time_exhausted() {
                    remaining = (chunks.len() - i) as u32;
                    info!(
                        account = acc,
                        remaining = remaining,
                        "time budget exhausted; returning partial"
                    );
                    break;
                }
                match self.pull_and_store(run_id, acc, *from, *to).await {
                    Ok((ins, skip)) => {
                        acc_added += ins;
                        acc_skipped += skip;
                        last_done_ts = *to;
                    }
                    Err(e) => {
                        warn!(account = acc, "chunk failed: {e}");
                        error = Some(e.to_string());
                        remaining = (chunks.len() - i) as u32;
                        break;
                    }
                }
            }

            self.store
                .finish_import_run(run_id, acc_added, acc_skipped, error.clone())
                .await?;
            out.rows_added += acc_added;
            out.remaining_chunks += remaining;
            out.per_account.push(AccountSyncOutcome {
                account_id: acc.clone(),
                rows_added: acc_added,
                rows_skipped: acc_skipped,
                last_completed_ts: last_done_ts,
                remaining_chunks: remaining,
                error,
            });
        }
        Ok(out)
    }

    fn time_exhausted(&self) -> bool {
        match self.deadline {
            None => false,
            Some(d) => Instant::now() + self.interval > d,
        }
    }

    /// Pull one chunk with up to 3 attempts on RateLimited/Transient errors.
    async fn pull_and_store(
        &self,
        run_id: i64,
        account: &str,
        from: i64,
        to: i64,
    ) -> Result<(u64, u64), DomainError> {
        let mut attempt: u32 = 0;
        loop {
            attempt += 1;
            self.limiter.wait().await;
            match self.api.statement(account, from, Some(to)).await {
                Ok(items) => {
                    let outcome = self
                        .store
                        .insert_statement_chunk(run_id, account, &items, to, now_unix())
                        .await
                        .map_err(|e| DomainError::from_err("store insert", e))?;
                    return Ok((outcome.rows_inserted, outcome.rows_skipped));
                }
                Err(DomainError::RateLimited(msg)) if attempt < 3 => {
                    warn!(attempt, "rate limited: {msg}; backing off 90s");
                    tokio::time::sleep(Duration::from_secs(90)).await;
                    continue;
                }
                Err(DomainError::Transient(msg)) if attempt < 3 => {
                    warn!(attempt, "transient: {msg}; retrying");
                    continue;
                }
                Err(e) => return Err(e),
            }
        }
    }
}
