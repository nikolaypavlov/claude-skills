use anyhow::{bail, Context, Result};

pub const CALDAV_BASE: &str = "https://caldav.icloud.com";
pub const IMAP_HOST: &str = "imap.mail.me.com";
pub const IMAP_PORT: u16 = 993;
pub const KEYCHAIN_SERVICE: &str = "icloud-mcp";

#[derive(Debug, Clone)]
pub struct Config {
    pub apple_id: String,
    pub app_password: String,
}

impl Config {
    pub fn load() -> Result<Self> {
        let apple_id = std::env::var("APPLE_ID")
            .context("APPLE_ID env var not set; export your full Apple ID, e.g. you@icloud.com")?
            .trim()
            .to_string();
        if apple_id.is_empty() {
            bail!("APPLE_ID is empty");
        }

        let app_password = match std::env::var("APPLE_APP_PASSWORD") {
            Ok(p) if !p.trim().is_empty() => p.trim().to_string(),
            _ => keychain_lookup(&apple_id).with_context(|| {
                format!(
                    "APPLE_APP_PASSWORD not set and not found in Keychain. \
                    Either export APPLE_APP_PASSWORD, or run: \
                    security add-generic-password -s {KEYCHAIN_SERVICE} -a {apple_id} -w <app-specific-password>"
                )
            })?,
        };

        Ok(Self {
            apple_id,
            app_password,
        })
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
