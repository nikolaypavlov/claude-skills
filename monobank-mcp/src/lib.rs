//! monobank-mcp library crate. The binary in `src/main.rs` wires these
//! modules into an MCP server / CLI; integration tests in `tests/` import
//! from here.

pub mod api;
pub mod backfill;
pub mod config;
pub mod error;
pub mod mcp;
pub mod migrations;
pub mod store;
pub mod sync;
pub mod types;
pub mod util;
