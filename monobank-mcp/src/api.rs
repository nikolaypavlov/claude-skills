//! Thin reqwest wrapper around the Monobank Personal API.
//!
//! Endpoints we use:
//!   GET /personal/client-info
//!   GET /personal/statement/{account}/{from}/{to}
//!
//! Auth: `X-Token` header. Rate limit: 1 request / 60s per token (we sleep
//! 61s as a safety margin in util::ratelimit before each call).

use std::time::Duration;

use reqwest::{header, Client, StatusCode};
use serde::de::DeserializeOwned;

use crate::error::DomainError;
use crate::types::{ClientInfo, MonoStatement};

/// Max items the API returns per statement call. The server may also truncate
/// the time range; we chunk to 31 days client-side which keeps us under both
/// limits in practice (rare exceptions trigger a `RateLimited` retry).
pub const STATEMENT_MAX_ITEMS: usize = 500;

#[derive(Clone)]
pub struct MonobankApi {
    client: Client,
    base: String,
    token: String,
}

impl MonobankApi {
    pub fn new(base: impl Into<String>, token: impl Into<String>) -> Result<Self, DomainError> {
        let client = Client::builder()
            .user_agent(concat!("monobank-mcp/", env!("CARGO_PKG_VERSION")))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|e| DomainError::from_err("reqwest build", e))?;
        Ok(Self {
            client,
            base: base.into(),
            token: token.into(),
        })
    }

    /// GET /personal/client-info
    pub async fn client_info(&self) -> Result<ClientInfo, DomainError> {
        let url = format!("{}/personal/client-info", self.base);
        self.get_json(&url).await
    }

    /// GET /personal/statement/{account}/{from}/{to}
    /// Times are unix seconds. `to` is optional - omit for "until now".
    pub async fn statement(
        &self,
        account: &str,
        from_ts: i64,
        to_ts: Option<i64>,
    ) -> Result<Vec<MonoStatement>, DomainError> {
        let url = match to_ts {
            Some(to) => format!(
                "{}/personal/statement/{}/{}/{}",
                self.base, account, from_ts, to
            ),
            None => format!("{}/personal/statement/{}/{}", self.base, account, from_ts),
        };
        self.get_json(&url).await
    }

    async fn get_json<T: DeserializeOwned>(&self, url: &str) -> Result<T, DomainError> {
        let resp = self
            .client
            .get(url)
            .header("X-Token", &self.token)
            .header(header::ACCEPT, "application/json")
            .send()
            .await
            .map_err(map_reqwest_send_err)?;

        let status = resp.status();
        if status.is_success() {
            let bytes = resp
                .bytes()
                .await
                .map_err(|e| DomainError::Transient(format!("read body: {e}")))?;
            return serde_json::from_slice::<T>(&bytes)
                .map_err(|e| DomainError::Permanent(format!("unexpected response shape: {e}")));
        }

        let body = resp.text().await.unwrap_or_default();
        Err(map_status(status, &body))
    }
}

fn map_status(status: StatusCode, body: &str) -> DomainError {
    let snippet = truncate(body, 256);
    match status.as_u16() {
        401 | 403 => DomainError::AuthFailed(format!("HTTP {status}: {snippet}")),
        429 => DomainError::RateLimited(format!("HTTP 429: {snippet}")),
        500..=599 => DomainError::Transient(format!("HTTP {status}: {snippet}")),
        400 => DomainError::InvalidInput(format!("HTTP 400: {snippet}")),
        _ => DomainError::Permanent(format!("HTTP {status}: {snippet}")),
    }
}

fn map_reqwest_send_err(e: reqwest::Error) -> DomainError {
    if e.is_timeout() || e.is_connect() {
        DomainError::Transient(format!("network: {e}"))
    } else {
        DomainError::from_err("reqwest send", e)
    }
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}...", &s[..max])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn map_status_classifies_429_as_rate_limited() {
        let e = map_status(StatusCode::TOO_MANY_REQUESTS, "slow down");
        assert!(matches!(e, DomainError::RateLimited(_)));
    }

    #[test]
    fn map_status_classifies_401_as_auth_failed() {
        let e = map_status(StatusCode::UNAUTHORIZED, "bad token");
        assert!(matches!(e, DomainError::AuthFailed(_)));
    }

    #[test]
    fn map_status_classifies_500_as_transient() {
        let e = map_status(StatusCode::INTERNAL_SERVER_ERROR, "oops");
        assert!(matches!(e, DomainError::Transient(_)));
    }
}
