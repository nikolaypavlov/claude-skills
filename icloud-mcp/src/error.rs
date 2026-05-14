//! Domain error taxonomy and MCP error mapping.
//!
//! `DomainError` lets the CalDAV and IMAP layers classify failures so that
//! `From<DomainError> for McpError` can map user input problems to
//! `invalid_params` and everything else to `internal_error`. This is what lets
//! an LLM client tell "fix your arguments" from "retry later".

use rmcp::ErrorData as McpError;

#[derive(Debug)]
pub enum DomainError {
    /// Resource (event UID, folder, calendar) does not exist.
    NotFound(String),
    /// Bad argument shape or content from the caller.
    InvalidInput(String),
    /// IMAP/CalDAV authentication failed.
    AuthFailed(String),
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

    pub fn transient<S: Into<String>>(msg: S) -> Self {
        Self::Transient(msg.into())
    }

    pub fn permanent<S: Into<String>>(msg: S) -> Self {
        Self::Permanent(msg.into())
    }

    /// Wrap any std error as `Permanent` with a context label. Use when the
    /// failure is genuinely unclassified - prefer the specific constructors.
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
                format!("auth failed (check APPLE_ID / app-specific password): {s}"),
                None,
            ),
            DomainError::Transient(s) => {
                McpError::internal_error(format!("transient failure (safe to retry): {s}"), None)
            }
            DomainError::Permanent(s) => McpError::internal_error(s, None),
        }
    }
}

/// Tag a domain error with a tool/operation name so the resulting MCP error
/// reads "<context>: <error>" - keeps logs and LLM messages contextual.
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
        let mcp: McpError = DomainError::not_found("event xyz").into();
        assert_eq!(mcp.code, ErrorCode::INVALID_PARAMS);
        assert!(mcp.message.contains("not found"));
    }

    #[test]
    fn invalid_input_maps_to_invalid_params() {
        let mcp: McpError = DomainError::invalid("bad address").into();
        assert_eq!(mcp.code, ErrorCode::INVALID_PARAMS);
    }

    #[test]
    fn transient_maps_to_internal_error() {
        let mcp: McpError = DomainError::transient("timeout").into();
        assert_eq!(mcp.code, ErrorCode::INTERNAL_ERROR);
        assert!(mcp.message.contains("retry"));
    }

    #[test]
    fn to_mcp_prepends_context() {
        let mcp = to_mcp("calendar_get_event", DomainError::not_found("abc"));
        assert!(mcp.message.starts_with("calendar_get_event:"));
    }
}
