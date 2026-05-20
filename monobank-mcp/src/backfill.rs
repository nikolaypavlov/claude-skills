//! Cold-start backfill orchestration.
//!
//! Differences from incremental sync:
//!   - Caller supplies `--from`. If absent, we use the earliest
//!     `opened_at` across selected accounts, or `now - 365d` as a safe
//!     fallback when `client-info` returns no `openedAt`.
//!   - We seed `mono_sync_state.last_completed_ts = from_ts` before
//!     starting so the sync engine has a cursor to advance.
//!   - No wall-clock budget; resumable on Ctrl-C because every chunk is
//!     atomic.

use std::time::Duration;

use anyhow::Result;
use tracing::info;

use crate::api::MonobankApi;
use crate::store::Store;
use crate::sync::{SyncEngine, SyncOutcome};
use crate::util::ratelimit::RateLimiter;
use crate::util::time::now_unix;

const FALLBACK_LOOKBACK_SECONDS: i64 = 365 * 24 * 60 * 60;

#[derive(Clone)]
pub struct BackfillEngine {
    api: MonobankApi,
    store: Store,
    limiter: RateLimiter,
    interval: Duration,
}

impl BackfillEngine {
    pub fn new(api: MonobankApi, store: Store, limiter: RateLimiter, interval: Duration) -> Self {
        Self {
            api,
            store,
            limiter,
            interval,
        }
    }

    /// Pull every account from `from_ts` (or default) to "now", inclusive.
    /// If `account_ids` is empty, sync the entire `mono_accounts` table.
    pub async fn run(&self, account_ids: Vec<String>, from_ts: Option<i64>) -> Result<SyncOutcome> {
        // 1) Discover accounts via API and persist them locally. Without the
        // account row backfill cannot seed sync_state.
        let info = self.api.client_info().await.map_err(anyhow::Error::from)?;
        for acc in &info.accounts {
            self.store.upsert_account(acc).await?;
        }
        // 2) Decide which accounts to backfill.
        let targets: Vec<String> = if account_ids.is_empty() {
            info.accounts.iter().map(|a| a.id.clone()).collect()
        } else {
            account_ids
        };
        let now = now_unix();
        let from = from_ts.unwrap_or_else(|| now - FALLBACK_LOOKBACK_SECONDS);
        info!(from, "backfill: seeding sync state");
        for id in &targets {
            self.store.seed_sync_state(id, from).await?;
        }
        // 3) Reuse the sync engine without a deadline. Backfill marks runs
        // as `Backfill` so audit reports can tell them apart from sync runs.
        let engine = SyncEngine::for_backfill(
            self.api.clone(),
            self.store.clone(),
            self.limiter.clone(),
            self.interval,
        );
        engine.run(&targets).await
    }
}
