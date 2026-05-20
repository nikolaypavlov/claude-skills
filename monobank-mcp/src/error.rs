//! Domain error taxonomy + MCP error mapping.
//!
//! `DomainError` lets the API, store, and sync layers classify failures so
//! that `From<DomainError> for McpError` can map user input problems to
//! `invalid_params`, transient/network problems to a retryable
//! `internal_error`, and configuration problems to a clearly-labelled
//! `internal_error` with a hint to run `/monobank-mcp:setup`.

use rmcp::ErrorData as McpError;

/// Errors classified by recoverability so the MCP / CLI layer can map
/// them to the right user-facing surface (e.g. retry-able vs ask-user-
/// to-reconfigure). Marked `#[non_exhaustive]` so future variants
/// (Maintenance, QuotaExceeded, etc.) don't break downstream
/// `match`/`matches!` callers.
#[derive(Debug)]
#[non_exhaustive]
pub enum DomainError {
    /// Resource (account id, range) does not exist.
    NotFound(String),
    /// Bad argument shape or content from the caller.
    InvalidInput(String),
    /// Monobank API rejected the token (401/403) or it is missing locally.
    AuthFailed(String),
    /// Rate limit hit; safe to retry after backoff.
    RateLimited(String),
    /// Transient network/protocol failure - safe to retry.
    Transient(String),
    /// Server-side or library failure that retrying will not fix.
    Permanent(String),
}

impl DomainError {
    pub fn not_found<S: Into<String>>(msg: S) -> Self {
        Self::NotFound(msg.into())
    }

    pub fn invalid<S: Into<String>>(msg: S) -> Self {
        Self::InvalidInput(msg.into())
    }

    pub fn auth<S: Into<String>>(msg: S) -> Self {
        Self::AuthFailed(msg.into())
    }

    pub fn rate_limited<S: Into<String>>(msg: S) -> Self {
        Self::RateLimited(msg.into())
    }

    pub fn transient<S: Into<String>>(msg: S) -> Self {
        Self::Transient(msg.into())
    }

    pub fn permanent<S: Into<String>>(msg: S) -> Self {
        Self::Permanent(msg.into())
    }

    pub fn from_err<E: std::fmt::Display>(context: &str, e: E) -> Self {
        Self::Permanent(format!("{context}: {e}"))
    }
}

impl std::fmt::Display for DomainError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotFound(s) => write!(f, "not found: {s}"),
            Self::InvalidInput(s) => write!(f, "invalid input: {s}"),
            Self::AuthFailed(s) => write!(f, "auth failed: {s}"),
            Self::RateLimited(s) => write!(f, "rate limited: {s}"),
            Self::Transient(s) => write!(f, "transient: {s}"),
            Self::Permanent(s) => write!(f, "{s}"),
        }
    }
}

impl std::error::Error for DomainError {}

impl From<DomainError> for McpError {
    fn from(e: DomainError) -> Self {
        match e {
            DomainError::NotFound(s) => McpError::invalid_params(format!("not found: {s}"), None),
            DomainError::InvalidInput(s) => McpError::invalid_params(s, None),
            DomainError::AuthFailed(s) => McpError::internal_error(
                format!("monobank token rejected or missing: {s}. Run /monobank-mcp:setup"),
                None,
            ),
            DomainError::RateLimited(s) => {
                McpError::internal_error(format!("rate limited: {s} (safe to retry)"), None)
            }
            DomainError::Transient(s) => {
                McpError::internal_error(format!("transient failure (safe to retry): {s}"), None)
            }
            DomainError::Permanent(s) => McpError::internal_error(s, None),
        }
    }
}

pub fn to_mcp(context: &str, e: DomainError) -> McpError {
    let inner: McpError = e.into();
    McpError::new(
        inner.code,
        format!("{context}: {}", inner.message),
        inner.data,
    )
}

pub fn invalid_params<S: Into<String>>(msg: S) -> McpError {
    McpError::invalid_params(msg.into(), None)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rmcp::model::ErrorCode;

    #[test]
    fn not_found_maps_to_invalid_params() {
        let mcp: McpError = DomainError::not_found("account xyz").into();
        assert_eq!(mcp.code, ErrorCode::INVALID_PARAMS);
    }

    #[test]
    fn auth_failed_maps_to_internal_error_with_setup_hint() {
        let mcp: McpError = DomainError::auth("401").into();
        assert_eq!(mcp.code, ErrorCode::INTERNAL_ERROR);
        assert!(mcp.message.contains("/monobank-mcp:setup"));
    }

    #[test]
    fn transient_message_mentions_retry() {
        let mcp: McpError = DomainError::transient("timeout").into();
        assert!(mcp.message.contains("retry"));
    }

    #[test]
    fn to_mcp_prepends_context() {
        let err = to_mcp("ensure_synced", DomainError::not_found("acc 1"));
        assert!(err.message.starts_with("ensure_synced:"));
    }
}
