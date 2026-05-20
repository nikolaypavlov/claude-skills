//! monobank-mcp entry point.
//!
//! Subcommands:
//!   init       configure (token in Keychain or env), write config.toml
//!   accounts   refresh account list from /personal/client-info
//!   backfill   cold-start backfill
//!   sync       manual incremental sync (no time budget)
//!   serve      run MCP server on stdio (default - used by Claude Desktop)
//!   query      debug helper: invoke a tool from the CLI
//!
//! With no subcommand we run `serve` so the `.mcp.json` launch script does
//! not need to know about CLI args.

use std::path::PathBuf;
use std::time::Duration;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use rmcp::{transport::stdio, ServiceExt};
use tracing_subscriber::EnvFilter;

use monobank_mcp::api::MonobankApi;
use monobank_mcp::backfill::BackfillEngine;
use monobank_mcp::config::{Config, KEYCHAIN_ACCOUNT, KEYCHAIN_SERVICE};
use monobank_mcp::mcp::MonobankServer;
use monobank_mcp::store::Store;
use monobank_mcp::sync::SyncEngine;
use monobank_mcp::types::RunSource;
use monobank_mcp::util::ratelimit::RateLimiter;
use monobank_mcp::util::time::{now_unix, parse_date_unix};

#[derive(Parser, Debug)]
#[command(name = "monobank-mcp", version, about, long_about = None)]
struct Cli {
    #[command(subcommand)]
    cmd: Option<Cmd>,
    /// Run the binary once and dump JSON probe output (used by /monobank-mcp:setup).
    #[arg(long, global = true)]
    probe: bool,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Configure the plugin: capture token + write config.toml.
    Init {
        /// Read the token from stdin (e.g. printf '%s' "$TOK" | monobank-mcp init --stdin).
        #[arg(long)]
        stdin: bool,
    },
    /// Refresh the local mono_accounts table from /personal/client-info.
    Accounts,
    /// Cold-start backfill. Without --from defaults to "now - 365 days".
    Backfill {
        #[arg(long)]
        from: Option<String>,
        #[arg(long)]
        account: Option<String>,
    },
    /// Incremental sync with no wall-clock budget.
    Sync {
        #[arg(long)]
        account: Option<String>,
    },
    /// Run the MCP stdio server (default if no subcommand is given).
    Serve,
    /// Probe credentials and report JSON (used by /monobank-mcp:setup).
    Probe,
}

#[tokio::main]
async fn main() -> Result<()> {
    install_tracing();
    let cli = Cli::parse();
    if cli.probe {
        return run_probe().await;
    }
    match cli.cmd.unwrap_or(Cmd::Serve) {
        Cmd::Init { stdin } => run_init(stdin).await,
        Cmd::Accounts => run_accounts().await,
        Cmd::Backfill { from, account } => run_backfill(from.as_deref(), account).await,
        Cmd::Sync { account } => run_sync(account).await,
        Cmd::Serve => run_serve().await,
        Cmd::Probe => run_probe().await,
    }
}

fn install_tracing() {
    let filter_spec = std::env::var("MONOBANK_MCP_LOG")
        .or_else(|_| std::env::var("RUST_LOG"))
        .unwrap_or_else(|_| "monobank_mcp=info".to_string());
    let _ = tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::new(filter_spec))
        .with_writer(std::io::stderr)
        .with_ansi(false)
        .try_init();
}

async fn run_serve() -> Result<()> {
    tracing::info!(version = env!("CARGO_PKG_VERSION"), "monobank-mcp starting");
    let server = match Config::try_load() {
        Some(cfg) => {
            tracing::info!(source = ?cfg.token_source, "config loaded");
            let store = Store::open(&cfg.db_path)?;
            MonobankServer::new(cfg, store).await?
        }
        None => {
            tracing::warn!(
                "no MONOBANK_TOKEN env var and no keychain entry; \
                 starting in unconfigured mode - run /monobank-mcp:setup"
            );
            MonobankServer::unconfigured()
        }
    };
    let service = server
        .serve(stdio())
        .await
        .inspect_err(|e| tracing::error!("serve error: {e:?}"))?;
    service.waiting().await?;
    Ok(())
}

async fn run_init(read_stdin: bool) -> Result<()> {
    let token = if read_stdin {
        use std::io::Read;
        let mut buf = String::new();
        std::io::stdin().read_to_string(&mut buf)?;
        buf.trim().to_string()
    } else {
        rpassword_prompt("Paste your Monobank Personal API token (input hidden, no newline): ")?
    };
    if token.is_empty() {
        anyhow::bail!("empty token");
    }
    let entry = keyring::Entry::new(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)?;
    match entry.set_password(&token) {
        Ok(()) => {
            eprintln!("Stored token in keychain (service={KEYCHAIN_SERVICE}, account={KEYCHAIN_ACCOUNT}).");
            write_default_config(true)?;
        }
        Err(e) => {
            eprintln!("Keychain unavailable ({e}). Set MONOBANK_TOKEN env var instead, then re-run /monobank-mcp:setup.");
            write_default_config(false)?;
        }
    }
    Ok(())
}

fn write_default_config(token_in_keychain: bool) -> Result<()> {
    let data_dir = monobank_mcp::config::default_data_dir();
    std::fs::create_dir_all(&data_dir)?;
    let path: PathBuf = data_dir.join("config.toml");
    if path.exists() {
        eprintln!(
            "config.toml already exists at {} (left untouched)",
            path.display()
        );
        return Ok(());
    }
    let body = format!(
        "# monobank-mcp configuration. All fields optional; sensible defaults\n\
         # apply when commented out.\n\
         token_in_keychain = {token_in_keychain}\n\
         # data_dir = \"~/finances\"\n\
         # api_base = \"https://api.monobank.ua\"\n\
         # api_min_interval_seconds = 61\n\
         # ensure_synced_default_budget = 90\n\
         # sync_freshness_skip_seconds = 300\n"
    );
    std::fs::write(&path, body)?;
    eprintln!("Wrote {}", path.display());
    Ok(())
}

fn rpassword_prompt(label: &str) -> Result<String> {
    // Avoid a `rpassword` dep: prompt to stderr, read the line from stdin.
    use std::io::{BufRead, Write};
    eprint!("{label}");
    std::io::stderr().flush().ok();
    let stdin = std::io::stdin();
    let mut buf = String::new();
    stdin.lock().read_line(&mut buf)?;
    Ok(buf.trim().to_string())
}

async fn run_accounts() -> Result<()> {
    let cfg = Config::load().context("load config (token missing? run /monobank-mcp:setup)")?;
    let store = Store::open(&cfg.db_path)?;
    let api = MonobankApi::new(cfg.api_base.clone(), cfg.token.clone())
        .map_err(|e| anyhow::anyhow!("api init: {e}"))?;
    let info = api.client_info().await.map_err(anyhow::Error::from)?;
    for acc in &info.accounts {
        store.upsert_account(acc).await?;
    }
    let rows = store.list_accounts().await?;
    println!("{}", serde_json::to_string_pretty(&rows)?);
    Ok(())
}

async fn run_backfill(from: Option<&str>, account: Option<String>) -> Result<()> {
    let cfg = Config::load().context("load config (token missing? run /monobank-mcp:setup)")?;
    let store = Store::open(&cfg.db_path)?;
    let api = MonobankApi::new(cfg.api_base.clone(), cfg.token.clone())
        .map_err(|e| anyhow::anyhow!("api init: {e}"))?;
    let limiter = RateLimiter::new(Duration::from_secs(cfg.api_min_interval_seconds));
    let from_ts = match from {
        Some(s) => Some(parse_date_unix(s).map_err(anyhow::Error::msg)?),
        None => None,
    };
    let targets: Vec<String> = account.into_iter().collect();
    let engine = BackfillEngine {
        api,
        store,
        limiter,
        interval: Duration::from_secs(cfg.api_min_interval_seconds),
    };
    let outcome = engine.run(targets, from_ts).await?;
    println!("{}", serde_json::to_string_pretty(&outcome)?);
    Ok(())
}

async fn run_sync(account: Option<String>) -> Result<()> {
    let cfg = Config::load().context("load config (token missing? run /monobank-mcp:setup)")?;
    let store = Store::open(&cfg.db_path)?;
    let api = MonobankApi::new(cfg.api_base.clone(), cfg.token.clone())
        .map_err(|e| anyhow::anyhow!("api init: {e}"))?;
    let limiter = RateLimiter::new(Duration::from_secs(cfg.api_min_interval_seconds));
    let targets: Vec<String> = if let Some(id) = account {
        vec![id]
    } else {
        store
            .list_accounts()
            .await?
            .into_iter()
            .map(|a| a.account_id)
            .collect()
    };
    let engine = SyncEngine {
        api,
        store,
        limiter,
        deadline: None,
        interval: Duration::from_secs(cfg.api_min_interval_seconds),
        freshness_skip_seconds: cfg.sync_freshness_skip_seconds,
        source: RunSource::Sync,
    };
    let outcome = engine.run(&targets).await?;
    println!("{}", serde_json::to_string_pretty(&outcome)?);
    Ok(())
}

/// `monobank-mcp --probe` (or `probe` subcommand): exercises the token by
/// calling /personal/client-info, writes a single JSON object to stdout.
async fn run_probe() -> Result<()> {
    let cfg = match Config::load() {
        Ok(c) => c,
        Err(e) => {
            let out = serde_json::json!({
                "ok": false,
                "stage": "config",
                "error": format!("{e:#}"),
            });
            println!("{}", serde_json::to_string_pretty(&out)?);
            return Ok(());
        }
    };
    let api = MonobankApi::new(cfg.api_base.clone(), cfg.token.clone());
    let info_result = match api {
        Ok(api) => api.client_info().await,
        Err(e) => Err(e),
    };
    let out = match info_result {
        Ok(info) => serde_json::json!({
            "ok": true,
            "credential_source": cfg.token_source,
            "client_id": info.client_id,
            "accounts_count": info.accounts.len(),
            "now": now_unix(),
        }),
        Err(e) => serde_json::json!({
            "ok": false,
            "credential_source": cfg.token_source,
            "error": e.to_string(),
        }),
    };
    println!("{}", serde_json::to_string_pretty(&out)?);
    Ok(())
}
