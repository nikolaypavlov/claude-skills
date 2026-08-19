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
//!
//! Reporting contract (0.4.0). The response distinguishes three things that
//! used to look identical from the outside:
//!   - "walked the window, nothing new"  -> status `synced`, chunks_fetched > 0
//!   - "never looked at this account"    -> status `unattempted`, chunks_fetched == 0
//!   - "walked it, but rows are missing" -> balance_checks[..].suspected_missing_rows
//!
//! `rows_added: 0` on its own proves none of them.

use std::time::{Duration, Instant};

use anyhow::Result;
use tracing::{debug, info, warn};

use crate::api::MonobankApi;
use crate::error::DomainError;
use crate::store::{BalanceCheck, Store};
use crate::types::RunSource;
use crate::util::ratelimit::RateLimiter;
use crate::util::time::{chunk_31d, now_unix};

/// What actually happened to one account in a run.
///
/// This exists because `rows_added: 0` is ambiguous on its own: the engine
/// emits it both for "queried the window, Monobank returned nothing" and for
/// "never queried this account at all". Before 0.4.0 nothing in the response
/// separated the two, and a budget-starved account was read as up to date.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AccountSyncStatus {
    /// No `mono_sync_state` row existed; the cursor was seeded at `now`
    /// without an API call. History before that point needs `backfill`.
    Seeded,
    /// Cursor and `last_sync_at` both sit inside `sync_freshness_skip_seconds`,
    /// so the previous run already covered the window. No API call.
    SkippedFresh,
    /// The cursor is already at or past `now`; no window to fetch.
    UpToDate,
    /// Every chunk this account needed was fetched and stored.
    Synced,
    /// Some chunks were fetched, some were not (wall-clock budget).
    Partial,
    /// The budget ran out before ANY chunk of this account was fetched. The
    /// account was not looked at; `rows_added: 0` here means nothing at all.
    Unattempted,
    /// A chunk failed; the rest of this account's chunks were skipped.
    Failed,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct AccountSyncOutcome {
    pub account_id: String,
    /// Read THIS (or `chunks_fetched`) before believing `rows_added: 0`.
    pub status: AccountSyncStatus,
    pub rows_added: u64,
    pub rows_skipped: u64,
    pub last_completed_ts: i64,
    /// Chunks the account needed this run: `chunks_fetched + remaining_chunks`.
    pub chunks_total: u32,
    /// Chunks actually pulled from the API and committed. Zero with
    /// `chunks_total > 0` means the account was never contacted.
    pub chunks_fetched: u32,
    /// Chunks left unfetched - unattempted (budget) plus, on failure, the
    /// chunk that errored and everything after it. `> 0` means this account
    /// holds an unchecked time window; nothing about it is known to be
    /// current.
    pub remaining_chunks: u32,
    /// Seconds the cursor trails "now" (`now - last_completed_ts`, clamped at
    /// 0). Diagnostic only. It measures how far behind the cursor is, NOT
    /// whether the data is current: a small gap with `remaining_chunks > 0`
    /// still means an unchecked window, and a day of unchecked window can
    /// hold an unbounded amount of real activity. Do not gate decisions on
    /// this field - use `remaining_chunks == 0`.
    pub gap_seconds: i64,
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
    /// Every account was fully walked: no account errored and none has a
    /// remaining chunk.
    ///
    /// This is the only field that licenses "the DB is current, skip the
    /// follow-up sync". It says nothing about rows that went missing INSIDE
    /// an already-walked window - read `balance_checks` for that.
    ///
    /// Design note (0.4.0): `caught_up` used to be independent of
    /// `remaining_chunks`, true whenever every cursor was within 24h of now.
    /// That is what made a budget-starved run look up to date while a card
    /// was missing 22 hours of spending. The cheap-retry case that the
    /// tolerance was meant to serve - a cursor trailing by seconds after a
    /// complete sync - is already handled correctly upstream by
    /// `sync_freshness_skip_seconds`, which skips the API call AND reports
    /// `remaining_chunks: 0`. So the tolerance bought nothing and cost
    /// correctness; there is no gap tolerance any more.
    pub caught_up: bool,
    /// Per-account balance reconciliation for the accounts in this run.
    /// Independent of `caught_up`: a mismatch here is a hole inside a window
    /// the cursor has already passed, which more syncing cannot close.
    pub balance_checks: Vec<BalanceCheck>,
}

impl SyncOutcome {
    pub fn partial(&self) -> bool {
        self.remaining_chunks > 0
    }

    /// Accounts whose stored balance disagrees with their newest stored
    /// transaction: rows are provably missing and need an explicit
    /// `backfill --from <date> --account <id>`.
    pub fn accounts_with_suspected_gaps(&self) -> Vec<&str> {
        self.balance_checks
            .iter()
            .filter(|c| c.suspected_missing_rows)
            .map(|c| c.account_id.as_str())
            .collect()
    }
}

/// Engine state for sync / backfill. Construct via the typed builders
/// (`for_backfill`, `for_sync`, `for_mcp`) rather than struct literals -
/// the field invariants (e.g. `freshness_skip_seconds = 0` for backfill)
/// are easy to get wrong otherwise.
#[derive(Clone)]
pub struct SyncEngine {
    api: MonobankApi,
    store: Store,
    limiter: RateLimiter,
    /// `None` means CLI-style: no deadline.
    deadline: Option<Instant>,
    /// Per-API call interval (the limiter enforces it; we use this for
    /// budgeting "is there time for one more call?").
    interval: Duration,
    /// Skip sync when `now - last_sync_at < freshness_skip_seconds`.
    freshness_skip_seconds: i64,
    source: RunSource,
    /// Backoff between retry attempts when the API surfaces a transient
    /// failure (429 or 5xx). Production uses `DEFAULT_RETRY_BACKOFF`.
    retry_backoff: Duration,
}

/// Production default for the retry backoff. Monobank publishes 1 req/60s
/// per token; bumping to 90s on a 429 leaves head-room for clock skew on
/// the API side.
pub const DEFAULT_RETRY_BACKOFF: Duration = Duration::from_secs(90);

impl SyncEngine {
    /// Engine wired for cold-start backfill: no deadline, no freshness
    /// skip (we want every chunk between `--from` and now).
    pub fn for_backfill(
        api: MonobankApi,
        store: Store,
        limiter: RateLimiter,
        interval: Duration,
    ) -> Self {
        Self {
            api,
            store,
            limiter,
            deadline: None,
            interval,
            freshness_skip_seconds: 0,
            source: RunSource::Backfill,
            retry_backoff: DEFAULT_RETRY_BACKOFF,
        }
    }

    /// Engine wired for CLI `sync`: no deadline; freshness skip honoured.
    pub fn for_sync(
        api: MonobankApi,
        store: Store,
        limiter: RateLimiter,
        interval: Duration,
        freshness_skip_seconds: i64,
    ) -> Self {
        Self {
            api,
            store,
            limiter,
            deadline: None,
            interval,
            freshness_skip_seconds,
            source: RunSource::Sync,
            retry_backoff: DEFAULT_RETRY_BACKOFF,
        }
    }

    /// Engine wired for the MCP `ensure_synced` tool: hard wall-clock
    /// deadline so the call returns before Claude's tool timeout.
    pub fn for_mcp(
        api: MonobankApi,
        store: Store,
        limiter: RateLimiter,
        interval: Duration,
        freshness_skip_seconds: i64,
        deadline: Instant,
    ) -> Self {
        Self {
            api,
            store,
            limiter,
            deadline: Some(deadline),
            interval,
            freshness_skip_seconds,
            source: RunSource::Sync,
            retry_backoff: DEFAULT_RETRY_BACKOFF,
        }
    }

    /// Failure-injection escape hatch: lets tests override every knob,
    /// notably `retry_backoff = ZERO` to keep the retry loop fast.
    /// Not part of the stable API - the `__` prefix signals "do not use".
    #[doc(hidden)]
    #[allow(clippy::too_many_arguments)]
    pub fn __for_test(
        api: MonobankApi,
        store: Store,
        limiter: RateLimiter,
        deadline: Option<Instant>,
        interval: Duration,
        freshness_skip_seconds: i64,
        source: RunSource,
        retry_backoff: Duration,
    ) -> Self {
        Self {
            api,
            store,
            limiter,
            deadline,
            interval,
            freshness_skip_seconds,
            source,
            retry_backoff,
        }
    }

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
                    // No sync_state row yet means this account was discovered by
                    // `accounts` / `client-info` but never backfilled. Rather
                    // than surfacing an error - which would break `monobank-mcp
                    // sync` cron jobs every time the user opens a new Monobank
                    // product - we seed the cursor at "now" and return a clean
                    // outcome for this run. Users who want historical rows run
                    // `backfill --from <date> --account <id>` explicitly.
                    self.store.seed_sync_state(acc, now).await?;
                    out.per_account.push(AccountSyncOutcome {
                        account_id: acc.clone(),
                        status: AccountSyncStatus::Seeded,
                        rows_added: 0,
                        rows_skipped: 0,
                        last_completed_ts: now,
                        chunks_total: 0,
                        chunks_fetched: 0,
                        remaining_chunks: 0,
                        gap_seconds: 0,
                        error: None,
                    });
                    continue;
                }
            };

            // Freshness skip: only meaningful for incremental sync, not for
            // explicit backfill. Backfill ignores this guard by construction
            // because it overrides `last_completed_ts` upstream (and uses
            // `freshness_skip_seconds = 0`).
            //
            // Both conditions must hold:
            //   1. `last_sync_at` is recent enough that re-pulling now would
            //      duplicate the previous run's work.
            //   2. `last_completed_ts` is also recent - guards against the
            //      "we last synced 10s ago BUT the cursor is 30 days behind
            //      (partial)" case, where the partial chunks still need
            //      fetching.
            // We use the same window for both so a freshly auto-seeded
            // account (cursor = now-at-seed) is skipped on the next sync
            // run within the configured freshness window, not just within
            // a 5-second tolerance.
            if let Some(state) = &state {
                let age = now - state.last_sync_at;
                let cursor_age = now - last_completed_ts;
                if age < self.freshness_skip_seconds && cursor_age < self.freshness_skip_seconds {
                    debug!(account = acc, age_s = age, "freshness skip");
                    out.per_account.push(AccountSyncOutcome {
                        account_id: acc.clone(),
                        status: AccountSyncStatus::SkippedFresh,
                        rows_added: 0,
                        rows_skipped: 0,
                        last_completed_ts,
                        chunks_total: 0,
                        chunks_fetched: 0,
                        remaining_chunks: 0,
                        gap_seconds: (now - last_completed_ts).max(0),
                        error: None,
                    });
                    continue;
                }
            }

            let chunks = chunk_31d(last_completed_ts, now);
            if chunks.is_empty() {
                out.per_account.push(AccountSyncOutcome {
                    account_id: acc.clone(),
                    status: AccountSyncStatus::UpToDate,
                    rows_added: 0,
                    rows_skipped: 0,
                    last_completed_ts,
                    chunks_total: 0,
                    chunks_fetched: 0,
                    remaining_chunks: 0,
                    gap_seconds: (now - last_completed_ts).max(0),
                    error: None,
                });
                continue;
            }

            out.skipped_all = false;
            let run_id = self.store.start_import_run(self.source).await?;
            let mut acc_added: u64 = 0;
            let mut acc_skipped: u64 = 0;
            let mut last_done_ts = last_completed_ts;
            let mut fetched: u32 = 0;
            let mut remaining: u32 = 0;
            let mut error: Option<String> = None;

            for (i, (from, to)) in chunks.iter().enumerate() {
                if self.time_exhausted() {
                    remaining = (chunks.len() - i) as u32;
                    info!(
                        account = acc,
                        fetched = fetched,
                        remaining = remaining,
                        "time budget exhausted; returning partial"
                    );
                    break;
                }
                match self.pull_and_store(run_id, acc, *from, *to).await {
                    Ok((ins, skip)) => {
                        acc_added += ins;
                        acc_skipped += skip;
                        fetched += 1;
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
            // Order matters: a failure is the headline even if earlier chunks
            // of the same account landed, and `Unattempted` must win over
            // `Partial` so a never-contacted account cannot hide behind a
            // zero row count.
            let status = if error.is_some() {
                AccountSyncStatus::Failed
            } else if remaining == 0 {
                AccountSyncStatus::Synced
            } else if fetched == 0 {
                AccountSyncStatus::Unattempted
            } else {
                AccountSyncStatus::Partial
            };
            out.per_account.push(AccountSyncOutcome {
                account_id: acc.clone(),
                status,
                rows_added: acc_added,
                rows_skipped: acc_skipped,
                last_completed_ts: last_done_ts,
                chunks_total: chunks.len() as u32,
                chunks_fetched: fetched,
                remaining_chunks: remaining,
                gap_seconds: (now - last_done_ts).max(0),
                error,
            });
        }
        // Caught up means every account was walked to the end: no errors and
        // no unfetched chunk anywhere. An unfetched chunk is an unchecked
        // window, and an unchecked window can hold any amount of activity -
        // so there is no gap tolerance here. The "cursor trails by seconds
        // after a complete sync" case is handled upstream by the freshness
        // skip, which reports `remaining_chunks: 0` honestly.
        out.caught_up = out
            .per_account
            .iter()
            .all(|a| a.error.is_none() && a.remaining_chunks == 0);
        // Balance reconciliation is orthogonal to the cursor: it catches rows
        // missing INSIDE a window the cursor already walked past, which no
        // amount of further syncing recovers. Kept out of `caught_up` on
        // purpose - see the field's doc comment.
        let mut checks = self.store.balance_checks().await?;
        checks.retain(|c| account_ids.contains(&c.account_id));
        out.balance_checks = checks;
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
                    warn!(
                        attempt,
                        backoff_ms = self.retry_backoff.as_millis() as u64,
                        "rate limited: {msg}; backing off",
                    );
                    tokio::time::sleep(self.retry_backoff).await;
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
