//! Configuration: data root + sync thresholds (TOML) + token resolution
//! (env primary, Keychain fallback).
//!
//! ```text
//! Priority order for the API token:
//!   1. MONOBANK_TOKEN env var
//!   2. Keychain entry under service = monobank-mcp, account = api-token
//!   3. Error - run /monobank-mcp:setup
//! ```

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

pub const KEYCHAIN_SERVICE: &str = "monobank-mcp";
pub const KEYCHAIN_ACCOUNT: &str = "api-token";
pub const API_BASE_DEFAULT: &str = "https://api.monobank.ua";

/// Where the API token was sourced from. Surfaced by diagnostics.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CredentialSource {
    Env,
    Keychain,
}

/// On-disk `config.toml` shape. All fields optional; defaults applied at load.
#[derive(Debug, Clone, Deserialize, Default)]
pub struct ConfigToml {
    #[serde(default)]
    pub data_dir: Option<PathBuf>,
    /// Override base URL (for testing or self-hosted proxies).
    #[serde(default)]
    pub api_base: Option<String>,
    /// Minimum seconds between two API requests. Default 61.
    #[serde(default)]
    pub api_min_interval_seconds: Option<u64>,
    /// ensure_synced default budget (seconds).
    #[serde(default)]
    pub ensure_synced_default_budget: Option<u64>,
    /// Skip sync when last_sync_at age (seconds) is below this. Default 300.
    #[serde(default)]
    pub sync_freshness_skip_seconds: Option<i64>,
    /// Token was stashed in Keychain at init time. Diagnostic flag only;
    /// the env var still takes precedence at runtime.
    #[serde(default)]
    pub token_in_keychain: bool,
}

#[derive(Debug, Clone)]
pub struct Config {
    pub data_dir: PathBuf,
    pub db_path: PathBuf,
    pub api_base: String,
    pub api_min_interval_seconds: u64,
    pub ensure_synced_default_budget: u64,
    pub sync_freshness_skip_seconds: i64,
    pub token: String,
    pub token_source: CredentialSource,
}

impl Config {
    /// Load both the file config and the token. Fails when the token is
    /// missing in env and Keychain.
    pub fn load() -> Result<Self> {
        let data_dir = default_data_dir();
        let toml_path = data_dir.join("config.toml");
        let file = read_toml(&toml_path)?;
        Self::from_parts(data_dir, file)
    }

    /// Non-fatal variant for MCP startup: returns None when the token is
    /// missing so the server can run in "unconfigured" mode.
    pub fn try_load() -> Option<Self> {
        Self::load().ok()
    }

    fn from_parts(default_data_dir: PathBuf, file: ConfigToml) -> Result<Self> {
        let data_dir = file.data_dir.unwrap_or(default_data_dir);
        std::fs::create_dir_all(&data_dir)
            .with_context(|| format!("failed to create data dir {}", data_dir.display()))?;
        let db_path = data_dir.join("data.db");
        let api_base = file
            .api_base
            .unwrap_or_else(|| API_BASE_DEFAULT.to_string());
        let api_min_interval_seconds = file.api_min_interval_seconds.unwrap_or(61);
        let ensure_synced_default_budget = file.ensure_synced_default_budget.unwrap_or(90);
        let sync_freshness_skip_seconds = file.sync_freshness_skip_seconds.unwrap_or(300);

        let (token, token_source) = resolve_token()?;

        Ok(Self {
            data_dir,
            db_path,
            api_base,
            api_min_interval_seconds,
            ensure_synced_default_budget,
            sync_freshness_skip_seconds,
            token,
            token_source,
        })
    }
}

pub fn default_data_dir() -> PathBuf {
    if let Ok(custom) = std::env::var("MONOBANK_MCP_DATA_DIR") {
        return PathBuf::from(custom);
    }
    if let Some(home) = home_dir() {
        home.join("finances")
    } else {
        PathBuf::from("./finances")
    }
}

pub fn home_dir() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

fn read_toml(path: &Path) -> Result<ConfigToml> {
    if !path.exists() {
        return Ok(ConfigToml::default());
    }
    let s = std::fs::read_to_string(path)
        .with_context(|| format!("read config.toml at {}", path.display()))?;
    let cfg: ConfigToml =
        toml::from_str(&s).with_context(|| format!("parse config.toml at {}", path.display()))?;
    Ok(cfg)
}

fn resolve_token() -> Result<(String, CredentialSource)> {
    if let Ok(t) = std::env::var("MONOBANK_TOKEN") {
        let trimmed = t.trim();
        if !trimmed.is_empty() {
            return Ok((trimmed.to_string(), CredentialSource::Env));
        }
    }
    // Keychain fallback (cross-platform via `keyring` crate).
    let entry = keyring::Entry::new(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT).with_context(|| {
        "MONOBANK_TOKEN env var is not set, and the keyring backend could not be opened. \
         Set MONOBANK_TOKEN, or run /monobank-mcp:setup."
    })?;
    let token = entry.get_password().with_context(|| {
        "MONOBANK_TOKEN env var is not set, and no token was found in the OS keychain. \
         Run /monobank-mcp:setup to store one."
    })?;
    let trimmed = token.trim();
    if trimmed.is_empty() {
        anyhow::bail!("keychain entry for monobank-mcp is empty; re-run /monobank-mcp:setup");
    }
    Ok((trimmed.to_string(), CredentialSource::Keychain))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // Env vars are process-global; serialise the two tests that mutate
    // MONOBANK_TOKEN so they don't race when cargo runs them in parallel.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn from_parts_applies_defaults() {
        let _g = ENV_LOCK.lock().unwrap();
        std::env::set_var("MONOBANK_TOKEN", "test-token-abc");
        let tmp = tempfile::tempdir().unwrap();
        let cfg = Config::from_parts(tmp.path().to_path_buf(), ConfigToml::default()).unwrap();
        std::env::remove_var("MONOBANK_TOKEN");
        assert_eq!(cfg.api_min_interval_seconds, 61);
        assert_eq!(cfg.ensure_synced_default_budget, 90);
        assert_eq!(cfg.sync_freshness_skip_seconds, 300);
        assert_eq!(cfg.api_base, API_BASE_DEFAULT);
        assert_eq!(cfg.token, "test-token-abc");
        assert_eq!(cfg.token_source, CredentialSource::Env);
        assert_eq!(cfg.db_path.file_name().unwrap(), "data.db");
    }

    #[test]
    fn from_parts_respects_overrides() {
        let _g = ENV_LOCK.lock().unwrap();
        std::env::set_var("MONOBANK_TOKEN", "x");
        let tmp = tempfile::tempdir().unwrap();
        let file = ConfigToml {
            data_dir: Some(tmp.path().to_path_buf()),
            api_base: Some("http://localhost:9999".into()),
            api_min_interval_seconds: Some(1),
            ensure_synced_default_budget: Some(10),
            sync_freshness_skip_seconds: Some(60),
            token_in_keychain: false,
        };
        let cfg = Config::from_parts(PathBuf::from("/unused"), file).unwrap();
        std::env::remove_var("MONOBANK_TOKEN");
        assert_eq!(cfg.api_base, "http://localhost:9999");
        assert_eq!(cfg.api_min_interval_seconds, 1);
        assert_eq!(cfg.ensure_synced_default_budget, 10);
        assert_eq!(cfg.sync_freshness_skip_seconds, 60);
        assert_eq!(cfg.data_dir, tmp.path());
    }
}
