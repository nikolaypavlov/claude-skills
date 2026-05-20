//! Single-token rate limiter for the Monobank API.
//!
//! Monobank publishes one request per 60 seconds per token. We model that
//! as a `Mutex<Option<Instant>>` holding the timestamp of the last issued
//! request. `wait()` sleeps until at least `interval` has elapsed, then
//! updates the cursor under the lock so concurrent callers serialize.
//!
//! Choosing a minimum of 61 seconds rather than 60 leaves a one-second
//! buffer for clock skew and network latency that has empirically been
//! sufficient to avoid 429s in practice.

use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::sync::Mutex;
use tokio::time::sleep;

#[derive(Clone)]
pub struct RateLimiter {
    interval: Duration,
    last: Arc<Mutex<Option<Instant>>>,
}

impl RateLimiter {
    pub fn new(interval: Duration) -> Self {
        Self {
            interval,
            last: Arc::new(Mutex::new(None)),
        }
    }

    /// Block until the configured interval has elapsed since the last
    /// successful `wait()` call. Marks "now" as the new cursor on return.
    pub async fn wait(&self) {
        let to_sleep = {
            let mut guard = self.last.lock().await;
            let now = Instant::now();
            let delay = match *guard {
                None => Duration::ZERO,
                Some(last) => {
                    let elapsed = now.saturating_duration_since(last);
                    self.interval.saturating_sub(elapsed)
                }
            };
            // Reserve the slot optimistically. If we update *after* the sleep
            // a second waiter could race past us during the sleep window.
            *guard = Some(now + delay);
            delay
        };
        if !to_sleep.is_zero() {
            sleep(to_sleep).await;
        }
    }

    /// Test-only: forget the cursor so the next `wait()` returns immediately.
    #[cfg(test)]
    pub async fn reset(&self) {
        *self.last.lock().await = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn first_call_does_not_block() {
        let rl = RateLimiter::new(Duration::from_secs(60));
        let start = Instant::now();
        rl.wait().await;
        // start_paused = true keeps the clock from advancing on its own.
        assert!(start.elapsed() < Duration::from_millis(10));
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn second_call_waits_full_interval() {
        let rl = RateLimiter::new(Duration::from_secs(60));
        rl.wait().await;
        let handle = tokio::spawn({
            let rl = rl.clone();
            async move { rl.wait().await }
        });
        // Tick by less than interval - the task should still be pending.
        tokio::time::sleep(Duration::from_secs(59)).await;
        assert!(!handle.is_finished());
        tokio::time::sleep(Duration::from_secs(2)).await;
        handle.await.unwrap();
    }
}
