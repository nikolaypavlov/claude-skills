use anyhow::{bail, Context, Result};

pub const CALDAV_BASE: &str = "https://caldav.icloud.com";
pub const IMAP_HOST: &str = "imap.mail.me.com";
pub const IMAP_PORT: u16 = 993;
pub const KEYCHAIN_SERVICE: &str = "icloud-mcp";

/// Where the app-specific password was sourced from. Surfaced by the
/// `auth_status` MCP tool and `--probe` CLI mode so the user can see how
/// the plugin found credentials.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CredentialSource {
    Env,
    Keychain,
}

#[derive(Debug, Clone)]
pub struct Config {
    pub apple_id: String,
    pub app_password: String,
    pub source: CredentialSource,
}

impl Config {
    /// Load credentials from env or Keychain. Returns Err if neither path
    /// yields a non-empty password - caller can decide whether to enter
    /// "unconfigured" mode or hard-fail.
    pub fn load() -> Result<Self> {
        let apple_id = std::env::var("APPLE_ID")
            .context("APPLE_ID env var not set; export your full Apple ID, e.g. you@icloud.com")?
            .trim()
            .to_string();
        if apple_id.is_empty() {
            bail!("APPLE_ID is empty");
        }

        let (app_password, source) = match std::env::var("APPLE_APP_PASSWORD") {
            Ok(p) if !p.trim().is_empty() => (p.trim().to_string(), CredentialSource::Env),
            _ => {
                let pw = keychain_lookup(&apple_id).with_context(|| {
                    if cfg!(target_os = "macos") {
                        format!(
                            "APPLE_APP_PASSWORD not set and not found in Keychain. \
                            Either export APPLE_APP_PASSWORD, or run: \
                            security add-generic-password -s {KEYCHAIN_SERVICE} -a {apple_id} -w <app-specific-password>"
                        )
                    } else {
                        "APPLE_APP_PASSWORD env var is required on non-macOS platforms (no Keychain fallback)".to_string()
                    }
                })?;
                (pw, CredentialSource::Keychain)
            }
        };

        Ok(Self {
            apple_id,
            app_password,
            source,
        })
    }

    /// Non-fatal variant: returns `Ok(None)` when credentials are absent so
    /// the MCP server can still start in unconfigured mode and surface a
    /// "run /icloud-mcp:setup" hint via `auth_status`.
    pub fn try_load() -> Option<Self> {
        Self::load().ok()
    }
}

#[cfg(target_os = "macos")]
fn keychain_lookup(apple_id: &str) -> Result<String> {
    use security_framework::passwords::get_generic_password;
    let bytes =
        get_generic_password(KEYCHAIN_SERVICE, apple_id).context("keychain item not found")?;
    String::from_utf8(bytes).context("keychain password is not valid UTF-8")
}

#[cfg(not(target_os = "macos"))]
fn keychain_lookup(_apple_id: &str) -> Result<String> {
    anyhow::bail!("keychain lookup is macOS-only")
}
