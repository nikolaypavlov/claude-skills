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

/// Byte-bounded truncation that respects UTF-8 char boundaries.
///
/// Monobank error bodies are Ukrainian and routinely contain Cyrillic
/// multi-byte sequences; raw `&s[..max]` would panic when `max` lands
/// inside a codepoint.
fn truncate(s: &str, max_bytes: usize) -> String {
    if s.len() <= max_bytes {
        return s.to_string();
    }
    // Walk char_indices until we either pass max_bytes or run out of
    // input. The last index that still fits becomes the cut point.
    let mut cut = 0usize;
    for (i, _) in s.char_indices() {
        if i > max_bytes {
            break;
        }
        cut = i;
    }
    format!("{}...", &s[..cut])
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

    #[test]
    fn truncate_handles_utf8_boundary() {
        // 3 Cyrillic chars + ASCII tail = 6 bytes Cyrillic + 5 ASCII.
        // Cutting at byte 5 lands mid-codepoint; truncate must back up.
        let s = "абвxyz";
        let out = truncate(s, 5);
        assert!(out.ends_with("..."), "got: {out}");
        // Only complete codepoints should remain before the ellipsis.
        let body = out.trim_end_matches("...");
        assert!(body.is_char_boundary(body.len()));
    }

    #[test]
    fn truncate_passes_through_short_strings() {
        assert_eq!(truncate("hi", 16), "hi");
    }

    #[test]
    fn truncate_handles_cyrillic_at_exact_boundary() {
        // 256-byte boundary cutting through Cyrillic - the scenario from
        // the bug report. We just need it to not panic and to produce
        // valid UTF-8.
        let s = "а".repeat(200); // 400 bytes
        let out = truncate(&s, 256);
        assert!(std::str::from_utf8(out.as_bytes()).is_ok());
        assert!(out.ends_with("..."));
    }
}
