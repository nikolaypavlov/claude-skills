//! IMAP client for iCloud Mail.
//!
//! - TLS via `tokio-rustls` with platform native certs.
//! - Connection pool: one warm `Session` reused across tool calls within
//!   `IDLE_MAX`. Each `acquire()` does a `NOOP` to confirm the session is
//!   still alive and reconnects if not.
//! - Read tools: list_folders, search, get_message.
//! - Create tool: create_draft (APPENDs the message to the Drafts folder
//!   with the `\Draft` flag; never sends).
//!
//! Pool diagram:
//!
//! ```text
//!     acquire()
//!       │
//!       ├── Some(p) and idle < 5min ──> NOOP ──> OK: reuse
//!       │                                  └──> Err: drop, login
//!       └── None or expired ───────────────────> login, store
//! ```

use std::sync::Arc;
use std::time::{Duration, Instant};

use async_imap::imap_proto;
use async_imap::types::{Fetch, Flag, Name, NameAttribute};
use async_imap::Session;
use chrono::{DateTime, Utc};
use futures_util::stream::TryStreamExt;
use lettre::message::{Mailbox, MultiPart, SinglePart};
use mail_parser::{MessageParser, MimeHeaders};
use rustls::ClientConfig;
use rustls_pki_types::ServerName;
use tokio::net::TcpStream;
use tokio::sync::Mutex;
use tokio_rustls::client::TlsStream;
use tokio_rustls::TlsConnector;
use uuid::Uuid;

use crate::config::{Config, IMAP_HOST, IMAP_PORT};
use crate::error::DomainError;
use crate::timeout::{with_timeout, IMAP_COMMAND, IMAP_LOGIN, TCP_CONNECT, TLS_HANDSHAKE};

type ImapSession = Session<TlsStream<TcpStream>>;

const IDLE_MAX: Duration = Duration::from_secs(5 * 60);
const DEFAULT_BODY_CAP: u32 = 512 * 1024;
const HTML2MD_OFFTHREAD_THRESHOLD: usize = 100_000;

#[derive(Debug, Clone, serde::Serialize)]
pub struct Folder {
    pub name: String,
    pub special_use: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct MailSummary {
    pub uid: u32,
    pub folder: String,
    pub from: String,
    pub to: Vec<String>,
    pub subject: String,
    pub date: Option<String>,
    pub flags: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct AttachmentMeta {
    pub filename: Option<String>,
    pub mime: String,
    pub size: u32,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct MailDetail {
    pub uid: u32,
    pub folder: String,
    pub from: String,
    pub to: Vec<String>,
    pub cc: Vec<String>,
    pub subject: String,
    pub date: Option<String>,
    pub body: String,
    pub body_format: String,
    pub attachments: Vec<AttachmentMeta>,
    pub total_size_bytes: u32,
    pub truncated: bool,
}

#[derive(Debug, Clone, Default)]
pub struct SearchCriteria {
    pub from: Option<String>,
    pub subject: Option<String>,
    pub text: Option<String>,
    pub since: Option<DateTime<Utc>>,
    pub before: Option<DateTime<Utc>>,
    pub unseen: bool,
}

#[derive(Debug, Clone)]
pub struct DraftParams {
    pub from: String,
    pub to: Vec<String>,
    pub cc: Vec<String>,
    pub bcc: Vec<String>,
    pub subject: String,
    pub body: String,
    pub html: bool,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct DraftResult {
    pub folder: String,
    pub message_id: String,
    pub size_bytes: usize,
}

struct PooledSession {
    session: ImapSession,
    last_used: Instant,
    current_folder: Option<String>,
}

pub struct ImapClient {
    config: Arc<Config>,
    tls_config: Arc<ClientConfig>,
    pool: Mutex<Option<PooledSession>>,
}

impl ImapClient {
    pub fn new(config: Arc<Config>) -> Result<Self, DomainError> {
        let tls_config = build_tls_config()?;
        Ok(Self {
            config,
            tls_config: Arc::new(tls_config),
            pool: Mutex::new(None),
        })
    }

    async fn fresh_login(&self) -> Result<ImapSession, DomainError> {
        let tcp = with_timeout("IMAP TCP connect", TCP_CONNECT, async {
            TcpStream::connect((IMAP_HOST, IMAP_PORT))
                .await
                .map_err(|e| {
                    DomainError::transient(format!("connect {IMAP_HOST}:{IMAP_PORT}: {e}"))
                })
        })
        .await?;

        let sni = ServerName::try_from(IMAP_HOST.to_string())
            .map_err(|e| DomainError::permanent(format!("invalid server name: {e}")))?;
        let connector = TlsConnector::from(self.tls_config.clone());
        let tls = with_timeout("IMAP TLS handshake", TLS_HANDSHAKE, async {
            connector
                .connect(sni, tcp)
                .await
                .map_err(|e| DomainError::transient(format!("TLS handshake: {e}")))
        })
        .await?;

        let mut client = async_imap::Client::new(tls);
        with_timeout("IMAP greeting", IMAP_COMMAND, async {
            client
                .read_response()
                .await
                .map_err(|e| DomainError::transient(format!("read greeting: {e}")))?
                .ok_or_else(|| DomainError::transient("no IMAP greeting"))?;
            Ok(())
        })
        .await?;

        with_timeout("IMAP LOGIN", IMAP_LOGIN, async {
            client
                .login(&self.config.apple_id, &self.config.app_password)
                .await
                .map_err(|(e, _client)| DomainError::auth(format!("IMAP login: {e}")))
        })
        .await
    }

    /// Acquire the pooled session, validating it via `NOOP`. On any failure
    /// the session is dropped and a fresh one is logged in. Caller holds the
    /// mutex guard for the duration of the operation.
    async fn acquire(
        &self,
    ) -> Result<tokio::sync::MutexGuard<'_, Option<PooledSession>>, DomainError> {
        let mut guard = self.pool.lock().await;

        let reuse = match guard.as_mut() {
            Some(p) if p.last_used.elapsed() < IDLE_MAX => {
                match with_timeout("IMAP NOOP", IMAP_COMMAND, async {
                    p.session
                        .noop()
                        .await
                        .map_err(|e| DomainError::transient(format!("NOOP: {e}")))
                })
                .await
                {
                    Ok(()) => {
                        tracing::debug!("pool: reused warm session");
                        true
                    }
                    Err(e) => {
                        tracing::debug!(error = %e, "pool: NOOP failed, reconnecting");
                        false
                    }
                }
            }
            Some(_) => {
                tracing::debug!("pool: session expired (idle > 5m), reconnecting");
                false
            }
            None => false,
        };

        if !reuse {
            *guard = None;
            let session = self.fresh_login().await?;
            *guard = Some(PooledSession {
                session,
                last_used: Instant::now(),
                current_folder: None,
            });
            tracing::debug!("pool: fresh login");
        }

        Ok(guard)
    }

    pub async fn list_folders(&self) -> Result<Vec<Folder>, DomainError> {
        let mut guard = self.acquire().await?;
        let p = guard.as_mut().expect("session present after acquire");
        let folders = with_timeout("IMAP LIST", IMAP_COMMAND, async {
            let stream = p
                .session
                .list(Some(""), Some("*"))
                .await
                .map_err(|e| DomainError::transient(format!("LIST: {e}")))?;
            let names: Vec<Name> = stream
                .try_collect()
                .await
                .map_err(|e| DomainError::transient(format!("collect LIST: {e}")))?;
            Ok::<_, DomainError>(
                names
                    .into_iter()
                    .map(|n| Folder {
                        name: n.name().to_string(),
                        special_use: special_use(n.attributes()),
                    })
                    .collect::<Vec<_>>(),
            )
        })
        .await?;
        p.last_used = Instant::now();
        Ok(folders)
    }

    async fn ensure_folder(p: &mut PooledSession, folder: &str) -> Result<(), DomainError> {
        if p.current_folder.as_deref() == Some(folder) {
            return Ok(());
        }
        with_timeout("IMAP SELECT", IMAP_COMMAND, async {
            p.session
                .select(folder)
                .await
                .map_err(|e| DomainError::not_found(format!("SELECT {folder}: {e}")))
        })
        .await?;
        p.current_folder = Some(folder.to_string());
        Ok(())
    }

    pub async fn search(
        &self,
        folder: &str,
        criteria: &SearchCriteria,
        limit: u32,
    ) -> Result<Vec<MailSummary>, DomainError> {
        let query = build_search_query(criteria)?;

        let mut guard = self.acquire().await?;
        let p = guard.as_mut().expect("session present after acquire");
        Self::ensure_folder(p, folder).await?;

        let uids = with_timeout("IMAP UID SEARCH", IMAP_COMMAND, async {
            p.session
                .uid_search(&query)
                .await
                .map_err(|e| DomainError::transient(format!("UID SEARCH {query}: {e}")))
        })
        .await?;

        let mut uids: Vec<u32> = uids.into_iter().collect();
        uids.sort_unstable_by(|a, b| b.cmp(a)); // newest first
        uids.truncate(limit.max(1) as usize);

        if uids.is_empty() {
            p.last_used = Instant::now();
            return Ok(Vec::new());
        }

        let uid_set = uids
            .iter()
            .map(u32::to_string)
            .collect::<Vec<_>>()
            .join(",");

        let messages: Vec<Fetch> = with_timeout("IMAP UID FETCH ENVELOPE", IMAP_COMMAND, async {
            let stream = p
                .session
                .uid_fetch(&uid_set, "(UID FLAGS ENVELOPE)")
                .await
                .map_err(|e| DomainError::transient(format!("UID FETCH ENVELOPE: {e}")))?;
            stream
                .try_collect::<Vec<_>>()
                .await
                .map_err(|e| DomainError::transient(format!("collect FETCH: {e}")))
        })
        .await?;

        let mut out: Vec<MailSummary> = messages
            .iter()
            .filter_map(|m| summary_from_envelope(m, folder))
            .collect();
        out.sort_by_key(|m| std::cmp::Reverse(m.uid));
        p.last_used = Instant::now();
        Ok(out)
    }

    pub async fn get_message(
        &self,
        folder: &str,
        uid: u32,
        max_bytes: Option<u32>,
    ) -> Result<MailDetail, DomainError> {
        let cap = max_bytes.unwrap_or(DEFAULT_BODY_CAP);

        let mut guard = self.acquire().await?;
        let p = guard.as_mut().expect("session present after acquire");
        Self::ensure_folder(p, folder).await?;

        // Step 1: fetch metadata (SIZE + flags) so we know whether to truncate.
        let meta: Vec<Fetch> = with_timeout("IMAP UID FETCH meta", IMAP_COMMAND, async {
            let stream = p
                .session
                .uid_fetch(uid.to_string(), "(UID FLAGS RFC822.SIZE)")
                .await
                .map_err(|e| DomainError::transient(format!("UID FETCH meta: {e}")))?;
            stream
                .try_collect::<Vec<_>>()
                .await
                .map_err(|e| DomainError::transient(format!("collect meta: {e}")))
        })
        .await?;
        let head = meta
            .into_iter()
            .next()
            .ok_or_else(|| DomainError::not_found(format!("message uid={uid} in {folder}")))?;
        let total_size = head.size.unwrap_or(0);

        // Step 2: fetch headers + partial body when oversized; otherwise full RFC822.
        let truncated = total_size > cap;
        let body_bytes: Vec<u8> = if truncated {
            with_timeout("IMAP UID FETCH partial", IMAP_COMMAND, async {
                let part_spec = format!("(UID BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.{cap}>)");
                let stream = p
                    .session
                    .uid_fetch(uid.to_string(), &part_spec)
                    .await
                    .map_err(|e| DomainError::transient(format!("UID FETCH partial: {e}")))?;
                let msgs: Vec<Fetch> = stream
                    .try_collect()
                    .await
                    .map_err(|e| DomainError::transient(format!("collect partial: {e}")))?;
                let f = msgs
                    .into_iter()
                    .next()
                    .ok_or_else(|| DomainError::not_found(format!("message uid={uid}")))?;
                let mut out = Vec::new();
                if let Some(h) = f.header() {
                    out.extend_from_slice(h);
                }
                if let Some(b) = f.body() {
                    out.extend_from_slice(b);
                }
                Ok::<_, DomainError>(out)
            })
            .await?
        } else {
            with_timeout("IMAP UID FETCH RFC822", IMAP_COMMAND, async {
                let stream = p
                    .session
                    .uid_fetch(uid.to_string(), "(UID FLAGS RFC822)")
                    .await
                    .map_err(|e| DomainError::transient(format!("UID FETCH RFC822: {e}")))?;
                let msgs: Vec<Fetch> = stream
                    .try_collect()
                    .await
                    .map_err(|e| DomainError::transient(format!("collect RFC822: {e}")))?;
                let f = msgs
                    .into_iter()
                    .next()
                    .ok_or_else(|| DomainError::not_found(format!("message uid={uid}")))?;
                Ok::<_, DomainError>(
                    f.body()
                        .ok_or_else(|| DomainError::permanent("message has no body"))?
                        .to_vec(),
                )
            })
            .await?
        };

        p.last_used = Instant::now();
        // Release the lock before doing CPU-bound parsing and html2md.
        drop(guard);

        let parsed = MessageParser::default()
            .parse(body_bytes.as_slice())
            .ok_or_else(|| DomainError::permanent("failed to parse RFC 822"))?;
        detail_from_parsed(&parsed, folder, uid, total_size, truncated).await
    }

    pub async fn create_draft(&self, p: &DraftParams) -> Result<DraftResult, DomainError> {
        let (message_bytes, message_id) = build_rfc822(p).await?;

        let mut guard = self.acquire().await?;
        let pooled = guard.as_mut().expect("session present after acquire");
        let drafts_folder = find_drafts_folder(&mut pooled.session).await?;

        with_timeout("IMAP APPEND", IMAP_COMMAND, async {
            pooled
                .session
                .append(
                    &drafts_folder,
                    Some("(\\Draft \\Seen)"),
                    None,
                    message_bytes.as_slice(),
                )
                .await
                .map_err(|e| DomainError::transient(format!("APPEND to {drafts_folder}: {e}")))
        })
        .await?;
        pooled.last_used = Instant::now();
        // APPEND changes the mailbox but not the selected folder; current_folder
        // unaffected.
        Ok(DraftResult {
            folder: drafts_folder,
            message_id,
            size_bytes: message_bytes.len(),
        })
    }
}

// ---- helpers ----

fn build_tls_config() -> Result<ClientConfig, DomainError> {
    let mut roots = rustls::RootCertStore::empty();
    let native = rustls_native_certs::load_native_certs();
    if !native.errors.is_empty() {
        for e in &native.errors {
            tracing::warn!("native cert load warning: {e}");
        }
    }
    for cert in native.certs {
        let _ = roots.add(cert);
    }
    if roots.is_empty() {
        return Err(DomainError::permanent(
            "no native TLS root certificates available; install ca-certificates",
        ));
    }
    Ok(ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth())
}

fn special_use(attrs: &[NameAttribute<'_>]) -> Option<String> {
    for a in attrs {
        let label = match a {
            NameAttribute::All => "All",
            NameAttribute::Archive => "Archive",
            NameAttribute::Drafts => "Drafts",
            NameAttribute::Flagged => "Flagged",
            NameAttribute::Junk => "Junk",
            NameAttribute::Sent => "Sent",
            NameAttribute::Trash => "Trash",
            _ => continue,
        };
        return Some(label.to_string());
    }
    None
}

async fn find_drafts_folder(session: &mut ImapSession) -> Result<String, DomainError> {
    let names: Vec<Name> = with_timeout("IMAP LIST for drafts", IMAP_COMMAND, async {
        let stream = session
            .list(Some(""), Some("*"))
            .await
            .map_err(|e| DomainError::transient(format!("LIST: {e}")))?;
        stream
            .try_collect()
            .await
            .map_err(|e| DomainError::transient(format!("collect LIST: {e}")))
    })
    .await?;

    if let Some(n) = names.iter().find(|n| {
        n.attributes()
            .iter()
            .any(|a| matches!(a, NameAttribute::Drafts))
    }) {
        return Ok(n.name().to_string());
    }
    if let Some(n) = names
        .iter()
        .find(|n| n.name().eq_ignore_ascii_case("Drafts"))
    {
        return Ok(n.name().to_string());
    }
    Err(DomainError::not_found(
        "could not locate Drafts folder via \\Drafts special-use or name match",
    ))
}

/// Build an IMAP SEARCH query string from structured criteria.
///
/// - ASCII text terms become quoted strings.
/// - Non-ASCII triggers a `CHARSET UTF-8 ` prefix; the server (iCloud accepts
///   this) is responsible for decoding the quoted UTF-8 bytes.
/// - CR / LF in any text term are rejected to keep the IMAP protocol intact.
fn build_search_query(c: &SearchCriteria) -> Result<String, DomainError> {
    let mut needs_utf8 = false;
    let mut parts: Vec<String> = Vec::new();

    if c.unseen {
        parts.push("UNSEEN".to_string());
    }
    for (key, value) in [
        ("FROM", c.from.as_deref()),
        ("SUBJECT", c.subject.as_deref()),
        ("TEXT", c.text.as_deref()),
    ] {
        let Some(v) = value else {
            continue;
        };
        guard_no_crlf(key, v)?;
        if !v.is_ascii() {
            needs_utf8 = true;
        }
        parts.push(format!("{key} {}", quote_imap(v)?));
    }
    if let Some(dt) = c.since {
        parts.push(format!("SINCE {}", fmt_imap_date(dt)));
    }
    if let Some(dt) = c.before {
        parts.push(format!("BEFORE {}", fmt_imap_date(dt)));
    }

    let body = if parts.is_empty() {
        "ALL".to_string()
    } else {
        parts.join(" ")
    };

    Ok(if needs_utf8 {
        format!("CHARSET UTF-8 {body}")
    } else {
        body
    })
}

fn guard_no_crlf(field: &str, s: &str) -> Result<(), DomainError> {
    if s.contains('\r') || s.contains('\n') {
        return Err(DomainError::invalid(format!(
            "{field}: CR/LF not allowed in IMAP search terms"
        )));
    }
    Ok(())
}

fn quote_imap(s: &str) -> Result<String, DomainError> {
    if s.contains('\r') || s.contains('\n') {
        return Err(DomainError::invalid(
            "control chars not allowed in IMAP literal",
        ));
    }
    let escaped = s.replace('\\', "\\\\").replace('"', "\\\"");
    Ok(format!("\"{escaped}\""))
}

fn fmt_imap_date(dt: DateTime<Utc>) -> String {
    // IMAP date: dd-Mmm-yyyy, e.g. 14-May-2026
    dt.format("%d-%b-%Y").to_string()
}

fn flag_name(f: &Flag<'_>) -> String {
    match f {
        Flag::Seen => "\\Seen".into(),
        Flag::Answered => "\\Answered".into(),
        Flag::Flagged => "\\Flagged".into(),
        Flag::Deleted => "\\Deleted".into(),
        Flag::Draft => "\\Draft".into(),
        Flag::Recent => "\\Recent".into(),
        Flag::MayCreate => "\\*".into(),
        Flag::Custom(s) => s.to_string(),
    }
}

fn summary_from_envelope(f: &Fetch, folder: &str) -> Option<MailSummary> {
    let uid = f.uid?;
    let env = f.envelope()?;

    let from = env
        .from
        .as_ref()
        .and_then(|v| v.first())
        .map(format_proto_addr)
        .unwrap_or_default();
    let to = env
        .to
        .as_ref()
        .map(|v| v.iter().map(format_proto_addr).collect())
        .unwrap_or_default();
    let subject = env
        .subject
        .as_ref()
        .map(|s| String::from_utf8_lossy(s).into_owned())
        .unwrap_or_default();
    let date = env
        .date
        .as_ref()
        .map(|d| String::from_utf8_lossy(d).into_owned());
    let flags: Vec<String> = f.flags().map(|fl| flag_name(&fl)).collect();

    Some(MailSummary {
        uid,
        folder: folder.to_string(),
        from,
        to,
        subject,
        date,
        flags,
    })
}

fn format_proto_addr(a: &imap_proto::types::Address<'_>) -> String {
    let name = a
        .name
        .as_ref()
        .map(|b| String::from_utf8_lossy(b).into_owned());
    let mailbox = a
        .mailbox
        .as_ref()
        .map(|b| String::from_utf8_lossy(b).into_owned())
        .unwrap_or_default();
    let host = a
        .host
        .as_ref()
        .map(|b| String::from_utf8_lossy(b).into_owned())
        .unwrap_or_default();
    let email = if host.is_empty() {
        mailbox
    } else {
        format!("{mailbox}@{host}")
    };
    match name {
        Some(n) if !n.is_empty() => format!("\"{n}\" <{email}>"),
        _ => email,
    }
}

async fn detail_from_parsed(
    msg: &mail_parser::Message<'_>,
    folder: &str,
    uid: u32,
    total_size: u32,
    truncated: bool,
) -> Result<MailDetail, DomainError> {
    let from = msg
        .from()
        .and_then(first_addr)
        .map(format_parser_addr)
        .unwrap_or_default();
    let to = collect_addrs(msg.to());
    let cc = collect_addrs(msg.cc());
    let subject = msg.subject().unwrap_or("").to_string();
    let date = msg.date().map(|d| d.to_rfc3339());

    let (body, body_format) = if let Some(text) = msg.body_text(0) {
        (text.into_owned(), "text".to_string())
    } else if let Some(html) = msg.body_html(0) {
        let owned = html.into_owned();
        let md = html_to_markdown(owned).await;
        (md, "markdown".to_string())
    } else {
        (String::new(), "text".to_string())
    };

    let attachments: Vec<AttachmentMeta> = msg
        .attachments()
        .map(|att| AttachmentMeta {
            filename: att.attachment_name().map(String::from),
            mime: att
                .content_type()
                .map(|ct| {
                    let main = ct.ctype();
                    match ct.subtype() {
                        Some(s) => format!("{main}/{s}"),
                        None => main.to_string(),
                    }
                })
                .unwrap_or_else(|| "application/octet-stream".to_string()),
            size: u32::try_from(att.len()).unwrap_or(u32::MAX),
        })
        .collect();

    Ok(MailDetail {
        uid,
        folder: folder.to_string(),
        from,
        to,
        cc,
        subject,
        date,
        body,
        body_format,
        attachments,
        total_size_bytes: total_size,
        truncated,
    })
}

/// Convert HTML to markdown. For documents over 100 KB the work is offloaded
/// to `spawn_blocking` so it does not occupy an async runtime worker.
async fn html_to_markdown(html: String) -> String {
    if html.len() > HTML2MD_OFFTHREAD_THRESHOLD {
        match tokio::task::spawn_blocking(move || html2md::parse_html(&html)).await {
            Ok(s) => s,
            Err(e) => {
                tracing::warn!(error = %e, "html2md blocking task failed; returning empty");
                String::new()
            }
        }
    } else {
        html2md::parse_html(&html)
    }
}

fn first_addr<'a>(addr: &'a mail_parser::Address<'_>) -> Option<&'a mail_parser::Addr<'a>> {
    match addr {
        mail_parser::Address::List(list) => list.first(),
        mail_parser::Address::Group(groups) => groups.first().and_then(|g| g.addresses.first()),
    }
}

fn collect_addrs(addr: Option<&mail_parser::Address<'_>>) -> Vec<String> {
    let Some(a) = addr else {
        return Vec::new();
    };
    match a {
        mail_parser::Address::List(list) => list.iter().map(format_parser_addr).collect(),
        mail_parser::Address::Group(groups) => groups
            .iter()
            .flat_map(|g| g.addresses.iter().map(format_parser_addr))
            .collect(),
    }
}

fn format_parser_addr(a: &mail_parser::Addr<'_>) -> String {
    let email = a.address.as_deref().unwrap_or("");
    match a.name.as_deref() {
        Some(n) if !n.is_empty() => format!("\"{n}\" <{email}>"),
        _ => email.to_string(),
    }
}

async fn build_rfc822(p: &DraftParams) -> Result<(Vec<u8>, String), DomainError> {
    let from: Mailbox = p
        .from
        .parse()
        .map_err(|e| DomainError::invalid(format!("invalid From address {:?}: {e}", p.from)))?;
    let message_id = format!("<{}@icloud-mcp>", Uuid::new_v4());

    let mut builder = lettre::Message::builder()
        .from(from)
        .message_id(Some(message_id.clone()))
        .subject(&p.subject);
    for s in &p.to {
        let mb: Mailbox = s
            .parse()
            .map_err(|e| DomainError::invalid(format!("invalid To {s:?}: {e}")))?;
        builder = builder.to(mb);
    }
    for s in &p.cc {
        let mb: Mailbox = s
            .parse()
            .map_err(|e| DomainError::invalid(format!("invalid Cc {s:?}: {e}")))?;
        builder = builder.cc(mb);
    }
    for s in &p.bcc {
        let mb: Mailbox = s
            .parse()
            .map_err(|e| DomainError::invalid(format!("invalid Bcc {s:?}: {e}")))?;
        builder = builder.bcc(mb);
    }

    let msg = if p.html {
        let html_owned = p.body.clone();
        let plain = html_to_markdown(html_owned).await;
        builder
            .multipart(
                MultiPart::alternative()
                    .singlepart(SinglePart::plain(plain))
                    .singlepart(SinglePart::html(p.body.clone())),
            )
            .map_err(|e| DomainError::permanent(format!("build multipart: {e}")))?
    } else {
        builder
            .body(p.body.clone())
            .map_err(|e| DomainError::permanent(format!("build plain: {e}")))?
    };

    Ok((msg.formatted(), message_id))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn quote_imap_escapes_backslash_and_quote() {
        assert_eq!(quote_imap("hello").unwrap(), "\"hello\"");
        assert_eq!(quote_imap(r#"a"b"#).unwrap(), r#""a\"b""#);
        assert_eq!(quote_imap(r"a\b").unwrap(), r#""a\\b""#);
    }

    #[test]
    fn quote_imap_rejects_cr_lf() {
        assert!(quote_imap("line1\nline2").is_err());
        assert!(quote_imap("line1\rline2").is_err());
    }

    #[test]
    fn imap_date_uses_dd_mmm_yyyy() {
        let dt = Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap();
        assert_eq!(fmt_imap_date(dt), "05-Jan-2026");
    }

    #[test]
    fn search_query_empty_is_all() {
        let q = build_search_query(&SearchCriteria::default()).unwrap();
        assert_eq!(q, "ALL");
    }

    #[test]
    fn search_query_combines_filters_with_space() {
        let c = SearchCriteria {
            from: Some("alice@example.com".into()),
            subject: Some("hello".into()),
            unseen: true,
            ..Default::default()
        };
        let q = build_search_query(&c).unwrap();
        assert!(q.contains("UNSEEN"));
        assert!(q.contains(r#"FROM "alice@example.com""#));
        assert!(q.contains(r#"SUBJECT "hello""#));
        assert!(!q.starts_with("CHARSET"));
    }

    #[test]
    fn search_query_includes_date_bounds() {
        let c = SearchCriteria {
            since: Some(Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap()),
            before: Some(Utc.with_ymd_and_hms(2026, 2, 1, 0, 0, 0).unwrap()),
            ..Default::default()
        };
        let q = build_search_query(&c).unwrap();
        assert!(q.contains("SINCE 01-Jan-2026"));
        assert!(q.contains("BEFORE 01-Feb-2026"));
    }

    #[test]
    fn search_query_charset_utf8_for_cyrillic() {
        let c = SearchCriteria {
            subject: Some("Звіт".into()),
            ..Default::default()
        };
        let q = build_search_query(&c).unwrap();
        assert!(q.starts_with("CHARSET UTF-8 "));
        assert!(q.contains("SUBJECT"));
    }

    #[test]
    fn search_query_rejects_crlf() {
        let c = SearchCriteria {
            subject: Some("hi\nfoo".into()),
            ..Default::default()
        };
        assert!(build_search_query(&c).is_err());
    }

    #[test]
    fn flag_name_maps_system_flags() {
        assert_eq!(flag_name(&Flag::Seen), "\\Seen");
        assert_eq!(flag_name(&Flag::Flagged), "\\Flagged");
        assert_eq!(flag_name(&Flag::Draft), "\\Draft");
    }

    #[test]
    fn flag_name_passes_custom_through() {
        let f = Flag::Custom(std::borrow::Cow::Borrowed("$Important"));
        assert_eq!(flag_name(&f), "$Important");
    }

    #[test]
    fn special_use_maps_drafts() {
        let attrs = vec![NameAttribute::Drafts];
        assert_eq!(special_use(&attrs).as_deref(), Some("Drafts"));
    }

    #[test]
    fn special_use_returns_none_for_marked() {
        let attrs = vec![NameAttribute::Marked];
        assert_eq!(special_use(&attrs), None);
    }

    #[test]
    fn format_parser_addr_with_name() {
        let a = mail_parser::Addr {
            name: Some("Alice".into()),
            address: Some("alice@example.com".into()),
        };
        assert_eq!(format_parser_addr(&a), r#""Alice" <alice@example.com>"#);
    }

    #[test]
    fn format_parser_addr_no_name() {
        let a = mail_parser::Addr {
            name: None,
            address: Some("bob@example.com".into()),
        };
        assert_eq!(format_parser_addr(&a), "bob@example.com");
    }

    #[tokio::test]
    async fn build_rfc822_plain_includes_headers_and_body() {
        let p = DraftParams {
            from: "Me <me@example.com>".into(),
            to: vec!["You <you@example.com>".into()],
            cc: vec![],
            bcc: vec![],
            subject: "Hello".into(),
            body: "Body text".into(),
            html: false,
        };
        let (bytes, msg_id) = build_rfc822(&p).await.unwrap();
        let raw = std::str::from_utf8(&bytes).unwrap();
        assert!(msg_id.starts_with('<') && msg_id.ends_with("@icloud-mcp>"));
        assert!(
            raw.contains("From: \"Me\" <me@example.com>")
                || raw.contains("From: Me <me@example.com>")
        );
        assert!(raw.contains("To:"));
        assert!(raw.to_lowercase().contains("subject:"));
        assert!(raw.contains("Body text"));
    }

    #[tokio::test]
    async fn build_rfc822_html_produces_multipart() {
        let p = DraftParams {
            from: "me@example.com".into(),
            to: vec!["you@example.com".into()],
            cc: vec![],
            bcc: vec![],
            subject: "T".into(),
            body: "<p>hi</p>".into(),
            html: true,
        };
        let (bytes, _) = build_rfc822(&p).await.unwrap();
        let raw = std::str::from_utf8(&bytes).unwrap();
        assert!(raw.to_lowercase().contains("multipart/alternative"));
        assert!(raw.to_lowercase().contains("text/plain"));
        assert!(raw.to_lowercase().contains("text/html"));
    }

    #[tokio::test]
    async fn build_rfc822_rejects_bad_address() {
        let p = DraftParams {
            from: "not an email".into(),
            to: vec!["x@y.com".into()],
            cc: vec![],
            bcc: vec![],
            subject: "T".into(),
            body: "B".into(),
            html: false,
        };
        assert!(build_rfc822(&p).await.is_err());
    }
}
