//! Smoke tests for the MCP server-handler construction path.
//!
//! Tool-method invocations are private to the crate (the `#[tool]` macro
//! does not change visibility), so the deepest end-to-end coverage of the
//! tool flow lives in unit tests inside `src/mcp/tools.rs`. Here we only
//! confirm the public construction paths work:
//!   - `MonobankServer::unconfigured()` returns a `ServerHandler`.
//!   - `MonobankServer::new(cfg, store)` builds when given a valid Config
//!     pointing at a mock API base.

mod common;

use std::path::PathBuf;

use monobank_mcp::config::{Config, CredentialSource};
use monobank_mcp::mcp::MonobankServer;
use monobank_mcp::store::Store;

fn synth_cfg(server_url: String, data_dir: PathBuf) -> Config {
    Config {
        db_path: data_dir.join("data.db"),
        data_dir,
        api_base: server_url,
        api_min_interval_seconds: 0,
        ensure_synced_default_budget: 30,
        sync_freshness_skip_seconds: 0,
        token: "test-token".into(),
        token_source: CredentialSource::Env,
    }
}

#[tokio::test]
async fn unconfigured_server_builds() {
    let _ = MonobankServer::unconfigured();
}

#[tokio::test]
async fn configured_server_builds_with_mock_api() {
    let server = httpmock::MockServer::start_async().await;
    let _ = server;
    let dir = tempfile::tempdir().unwrap();
    let store = Store::open(&dir.path().join("data.db")).unwrap();
    let cfg = synth_cfg(server.base_url(), dir.path().to_path_buf());
    let _ = MonobankServer::new(cfg, store).await.unwrap();
}
