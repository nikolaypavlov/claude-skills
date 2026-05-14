use rmcp::ErrorData as McpError;

pub fn to_mcp<E: std::fmt::Display>(context: &str, e: E) -> McpError {
    McpError::internal_error(format!("{context}: {e}"), None)
}

pub fn invalid_params<S: Into<String>>(msg: S) -> McpError {
    McpError::invalid_params(msg.into(), None)
}
