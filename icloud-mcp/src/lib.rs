//! icloud-mcp library crate. The binary in `src/main.rs` wires these modules
//! into an MCP server; the library surface is what integration tests in
//! `tests/` import.

pub mod caldav;
pub mod config;
pub mod error;
pub mod imap_client;
pub mod timeout;
