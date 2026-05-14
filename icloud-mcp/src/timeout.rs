//! Network timeout wrapper.
//!
//! All remote calls go through `with_timeout` so a hung iCloud connection
//! never blocks the MCP server forever. A timeout becomes a `DomainError::Transient`
//! so the LLM client knows it is safe to retry.

use std::future::Future;
use std::time::Duration;

use crate::error::DomainError;

pub const TCP_CONNECT: Duration = Duration::from_secs(10);
pub const TLS_HANDSHAKE: Duration = Duration::from_secs(10);
pub const IMAP_LOGIN: Duration = Duration::from_secs(15);
pub const IMAP_COMMAND: Duration = Duration::from_secs(20);
pub const CALDAV_REQUEST: Duration = Duration::from_secs(20);

pub async fn with_timeout<F, T>(label: &str, dur: Duration, fut: F) -> Result<T, DomainError>
where
    F: Future<Output = Result<T, DomainError>>,
{
    match tokio::time::timeout(dur, fut).await {
        Ok(inner) => inner,
        Err(_) => Err(DomainError::transient(format!(
            "{label} timed out after {}s",
            dur.as_secs()
        ))),
    }
}
