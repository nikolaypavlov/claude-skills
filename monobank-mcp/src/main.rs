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
        // rpassword disables terminal echo so the token is not visible.
        // On a non-TTY (CI, piped stdin) rpassword falls back to a normal
        // line read - users running outside a terminal should prefer
        // `--stdin` and feed the token over a pipe.
        rpassword::prompt_password("Paste your Monobank Personal API token (input hidden): ")
            .context("read token from terminal")?
            .trim()
            .to_string()
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

/// Shared wiring for every CLI subcommand that talks to the API and the
/// store. Centralising avoids the "forgot to pass cfg.api_base" / "wrong
/// RateLimiter interval" drift across three near-identical setups.
struct CliRuntime {
    cfg: Config,
    store: Store,
    api: MonobankApi,
    limiter: RateLimiter,
}

fn load_runtime() -> Result<CliRuntime> {
    let cfg = Config::load().context("load config (token missing? run /monobank-mcp:setup)")?;
    let store = Store::open(&cfg.db_path)?;
    let api = MonobankApi::new(cfg.api_base.clone(), cfg.token.clone())
        .map_err(|e| anyhow::anyhow!("api init: {e}"))?;
    let limiter = RateLimiter::new(Duration::from_secs(cfg.api_min_interval_seconds));
    Ok(CliRuntime {
        cfg,
        store,
        api,
        limiter,
    })
}

async fn run_accounts() -> Result<()> {
    let rt = load_runtime()?;
    let info = rt.api.client_info().await.map_err(anyhow::Error::from)?;
    for acc in &info.accounts {
        rt.store.upsert_account(acc).await?;
    }
    let rows = rt.store.list_accounts().await?;
    println!("{}", serde_json::to_string_pretty(&rows)?);
    Ok(())
}

async fn run_backfill(from: Option<&str>, account: Option<String>) -> Result<()> {
    let rt = load_runtime()?;
    let from_ts = match from {
        Some(s) => Some(parse_date_unix(s).map_err(anyhow::Error::msg)?),
        None => None,
    };
    let targets: Vec<String> = account.into_iter().collect();
    let engine = BackfillEngine::new(
        rt.api,
        rt.store,
        rt.limiter,
        Duration::from_secs(rt.cfg.api_min_interval_seconds),
    );
    let outcome = engine.run(targets, from_ts).await?;
    println!("{}", serde_json::to_string_pretty(&outcome)?);
    bail_if_any_account_errored(&outcome)?;
    Ok(())
}

async fn run_sync(account: Option<String>) -> Result<()> {
    let rt = load_runtime()?;
    // Stalest cursor first. The CLI has no wall-clock budget so it always
    // finishes every account, but a Ctrl-C mid-run then leaves the accounts
    // that were furthest behind already done rather than untouched.
    let targets: Vec<String> = if let Some(id) = account {
        vec![id]
    } else {
        rt.store.list_account_ids_by_staleness().await?
    };
    let engine = SyncEngine::for_sync(
        rt.api,
        rt.store,
        rt.limiter,
        Duration::from_secs(rt.cfg.api_min_interval_seconds),
        rt.cfg.sync_freshness_skip_seconds,
    );
    let outcome = engine.run(&targets).await?;
    println!("{}", serde_json::to_string_pretty(&outcome)?);
    bail_if_any_account_errored(&outcome)?;
    Ok(())
}

/// Exit non-zero when any account reported a chunk error. cron jobs and CI
/// scripts otherwise see exit 0 even when every account 401'd or hit a
/// transient failure - the JSON payload still carries the detail.
fn bail_if_any_account_errored(outcome: &monobank_mcp::sync::SyncOutcome) -> Result<()> {
    let errored: Vec<&str> = outcome
        .per_account
        .iter()
        .filter_map(|a| a.error.as_deref().map(|_| a.account_id.as_str()))
        .collect();
    if errored.is_empty() {
        return Ok(());
    }
    anyhow::bail!(
        "{} account(s) reported errors: {}",
        errored.len(),
        errored.join(", ")
    );
}

/// `monobank-mcp --probe` (or `probe` subcommand): exercises the token by
/// calling /personal/client-info, writes a single JSON object to stdout.
///
/// Exit code matches the `ok` field: 0 on success, 1 on any failure. Shell
/// wrappers (the `/monobank-mcp:setup` slash command among them) rely on
/// `$?` rather than re-parsing JSON; surfacing failure only in the JSON
/// payload would silently report success.
async fn run_probe() -> Result<()> {
    let (out, ok) = build_probe_result().await;
    println!("{}", serde_json::to_string_pretty(&out)?);
    if !ok {
        std::process::exit(1);
    }
    Ok(())
}

async fn build_probe_result() -> (serde_json::Value, bool) {
    let cfg = match Config::load() {
        Ok(c) => c,
        Err(e) => {
            return (
                serde_json::json!({
                    "ok": false,
                    "stage": "config",
                    "error": format!("{e:#}"),
                }),
                false,
            );
        }
    };
    let api = MonobankApi::new(cfg.api_base.clone(), cfg.token.clone());
    let info_result = match api {
        Ok(api) => api.client_info().await,
        Err(e) => Err(e),
    };
    match info_result {
        Ok(info) => (
            serde_json::json!({
                "ok": true,
                "credential_source": cfg.token_source,
                "client_id": info.client_id,
                "accounts_count": info.accounts.len(),
                "now": now_unix(),
            }),
            true,
        ),
        Err(e) => (
            serde_json::json!({
                "ok": false,
                "credential_source": cfg.token_source,
                "error": e.to_string(),
            }),
            false,
        ),
    }
}
