//! IMAP client for iCloud Mail.
//!
//! - TLS via `tokio-rustls` with platform native certs.
//! - One connection per tool call (simple; iCloud handles it).
//! - Read tools: list_folders, search, get_message.
//! - Create tool: create_draft (APPENDs the message to the Drafts folder
//!   with the `\Draft` flag; never sends).

use std::sync::Arc;

use anyhow::{Context, Result, anyhow, bail};
use async_imap::Session;
use async_imap::imap_proto;
use async_imap::types::{Fetch, Name, NameAttribute};
use chrono::{DateTime, Utc};
use futures::stream::TryStreamExt;
use lettre::message::{Mailbox, MultiPart, SinglePart};
use mail_parser::{MessageParser, MimeHeaders};
use uuid::Uuid;
use rustls::ClientConfig;
use rustls_pki_types::ServerName;
use tokio::net::TcpStream;
use tokio_rustls::TlsConnector;
use tokio_rustls::client::TlsStream;

use crate::config::{Config, IMAP_HOST, IMAP_PORT};

type ImapSession = Session<TlsStream<TcpStream>>;

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
    pub attachments: Vec<String>,
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

pub struct ImapClient {
    config: Arc<Config>,
    tls_config: Arc<ClientConfig>,
}

impl ImapClient {
    pub fn new(config: Arc<Config>) -> Result<Self> {
        let tls_config = build_tls_config()?;
        Ok(Self {
            config,
            tls_config: Arc::new(tls_config),
        })
    }

    async fn login(&self) -> Result<ImapSession> {
        let tcp = TcpStream::connect((IMAP_HOST, IMAP_PORT))
            .await
            .with_context(|| format!("connect to {IMAP_HOST}:{IMAP_PORT}"))?;
        let sni = ServerName::try_from(IMAP_HOST.to_string()).context("invalid server name")?;
        let connector = TlsConnector::from(self.tls_config.clone());
        let tls = connector
            .connect(sni, tcp)
            .await
            .context("TLS handshake")?;

        let mut client = async_imap::Client::new(tls);
        let _greeting = client
            .read_response()
            .await
            .context("read greeting")?
            .ok_or_else(|| anyhow!("no IMAP greeting"))?;

        let session = client
            .login(&self.config.apple_id, &self.config.app_password)
            .await
            .map_err(|(e, _client)| anyhow!("IMAP login: {e}"))?;
        Ok(session)
    }

    pub async fn list_folders(&self) -> Result<Vec<Folder>> {
        let mut session = self.login().await?;
        let folders_stream = session
            .list(Some(""), Some("*"))
            .await
            .context("LIST")?;
        let names: Vec<Name> = folders_stream.try_collect().await.context("collect LIST")?;
        let folders: Vec<Folder> = names
            .into_iter()
            .map(|n| Folder {
                name: n.name().to_string(),
                special_use: special_use(n.attributes()),
            })
            .collect();
        let _ = session.logout().await;
        Ok(folders)
    }

    pub async fn search(
        &self,
        folder: &str,
        criteria: &SearchCriteria,
        limit: u32,
    ) -> Result<Vec<MailSummary>> {
        let mut session = self.login().await?;
        let _mailbox = session
            .select(folder)
            .await
            .with_context(|| format!("SELECT {folder}"))?;

        let query = build_search_query(criteria);
        let uids = session
            .uid_search(&query)
            .await
            .with_context(|| format!("UID SEARCH {query}"))?;
        let mut uids: Vec<u32> = uids.into_iter().collect();
        uids.sort_unstable_by(|a, b| b.cmp(a)); // newest first
        uids.truncate(limit.max(1) as usize);

        if uids.is_empty() {
            let _ = session.logout().await;
            return Ok(Vec::new());
        }

        let uid_set = uids
            .iter()
            .map(u32::to_string)
            .collect::<Vec<_>>()
            .join(",");
        let stream = session
            .uid_fetch(&uid_set, "(UID FLAGS ENVELOPE)")
            .await
            .context("UID FETCH ENVELOPE")?;
        let messages: Vec<Fetch> = stream.try_collect().await.context("collect FETCH")?;

        let mut out: Vec<MailSummary> = messages
            .iter()
            .filter_map(|m| summary_from_envelope(m, folder))
            .collect();
        out.sort_by(|a, b| b.uid.cmp(&a.uid));

        let _ = session.logout().await;
        Ok(out)
    }

    pub async fn get_message(&self, folder: &str, uid: u32) -> Result<MailDetail> {
        let mut session = self.login().await?;
        let _mailbox = session
            .select(folder)
            .await
            .with_context(|| format!("SELECT {folder}"))?;

        let stream = session
            .uid_fetch(uid.to_string(), "(UID FLAGS RFC822)")
            .await
            .context("UID FETCH RFC822")?;
        let messages: Vec<Fetch> = stream.try_collect().await.context("collect")?;
        let fetch = messages
            .into_iter()
            .next()
            .ok_or_else(|| anyhow!("message uid={uid} not found in {folder}"))?;
        let body_bytes = fetch
            .body()
            .ok_or_else(|| anyhow!("message has no body"))?
            .to_vec();
        let _ = session.logout().await;

        let parsed = MessageParser::default()
            .parse(body_bytes.as_slice())
            .ok_or_else(|| anyhow!("failed to parse RFC 822"))?;
        detail_from_parsed(&parsed, folder, uid)
    }

    pub async fn create_draft(&self, p: &DraftParams) -> Result<DraftResult> {
        let (message_bytes, message_id) = build_rfc822(p)?;
        let mut session = self.login().await?;
        let drafts_folder = find_drafts_folder(&mut session).await?;
        session
            .append(
                &drafts_folder,
                Some("(\\Draft \\Seen)"),
                None,
                message_bytes.as_slice(),
            )
            .await
            .with_context(|| format!("APPEND to {drafts_folder}"))?;
        let _ = session.logout().await;
        Ok(DraftResult {
            folder: drafts_folder,
            message_id,
            size_bytes: message_bytes.len(),
        })
    }
}

// ---- helpers ----

fn build_tls_config() -> Result<ClientConfig> {
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

async fn find_drafts_folder(session: &mut ImapSession) -> Result<String> {
    let stream = session.list(Some(""), Some("*")).await.context("LIST for drafts")?;
    let names: Vec<Name> = stream.try_collect().await?;
    if let Some(n) = names
        .iter()
        .find(|n| n.attributes().iter().any(|a| matches!(a, NameAttribute::Drafts)))
    {
        return Ok(n.name().to_string());
    }
    // Fallback: iCloud usually exposes a folder literally named "Drafts".
    if let Some(n) = names
        .iter()
        .find(|n| n.name().eq_ignore_ascii_case("Drafts"))
    {
        return Ok(n.name().to_string());
    }
    bail!("could not locate Drafts folder via \\Drafts special-use or name match");
}

fn build_search_query(c: &SearchCriteria) -> String {
    let mut parts: Vec<String> = Vec::new();
    if c.unseen {
        parts.push("UNSEEN".to_string());
    }
    if let Some(s) = &c.from {
        parts.push(format!("FROM {}", quote_imap(s)));
    }
    if let Some(s) = &c.subject {
        parts.push(format!("SUBJECT {}", quote_imap(s)));
    }
    if let Some(s) = &c.text {
        parts.push(format!("TEXT {}", quote_imap(s)));
    }
    if let Some(dt) = c.since {
        parts.push(format!("SINCE {}", fmt_imap_date(dt)));
    }
    if let Some(dt) = c.before {
        parts.push(format!("BEFORE {}", fmt_imap_date(dt)));
    }
    if parts.is_empty() {
        "ALL".to_string()
    } else {
        parts.join(" ")
    }
}

fn quote_imap(s: &str) -> String {
    let escaped = s.replace('\\', "\\\\").replace('"', "\\\"");
    format!("\"{escaped}\"")
}

fn fmt_imap_date(dt: DateTime<Utc>) -> String {
    // IMAP date: dd-Mmm-yyyy, e.g. 14-May-2026
    dt.format("%d-%b-%Y").to_string()
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
    let flags: Vec<String> = f.flags().map(|fl| format!("{fl:?}")).collect();

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

fn detail_from_parsed(
    msg: &mail_parser::Message<'_>,
    folder: &str,
    uid: u32,
) -> Result<MailDetail> {
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
        (html2md::parse_html(&html), "markdown".to_string())
    } else {
        (String::new(), "text".to_string())
    };

    let attachments: Vec<String> = msg
        .attachments()
        .filter_map(|att| att.attachment_name().map(String::from))
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
    })
}

fn first_addr<'a>(addr: &'a mail_parser::Address<'_>) -> Option<&'a mail_parser::Addr<'a>> {
    match addr {
        mail_parser::Address::List(list) => list.first(),
        mail_parser::Address::Group(groups) => groups.first().and_then(|g| g.addresses.first()),
    }
}

fn collect_addrs(addr: Option<&mail_parser::Address<'_>>) -> Vec<String> {
    let Some(a) = addr else { return Vec::new(); };
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

fn build_rfc822(p: &DraftParams) -> Result<(Vec<u8>, String)> {
    let from: Mailbox = p
        .from
        .parse()
        .with_context(|| format!("invalid From address: {}", p.from))?;
    let message_id = format!("<{}@icloud-mcp>", Uuid::new_v4());

    let mut builder = lettre::Message::builder()
        .from(from)
        .message_id(Some(message_id.clone()))
        .subject(&p.subject);
    for s in &p.to {
        let mb: Mailbox = s.parse().with_context(|| format!("invalid To: {s}"))?;
        builder = builder.to(mb);
    }
    for s in &p.cc {
        let mb: Mailbox = s.parse().with_context(|| format!("invalid Cc: {s}"))?;
        builder = builder.cc(mb);
    }
    for s in &p.bcc {
        let mb: Mailbox = s.parse().with_context(|| format!("invalid Bcc: {s}"))?;
        builder = builder.bcc(mb);
    }

    let msg = if p.html {
        let plain = html2md::parse_html(&p.body);
        builder
            .multipart(
                MultiPart::alternative()
                    .singlepart(SinglePart::plain(plain))
                    .singlepart(SinglePart::html(p.body.clone())),
            )
            .context("build multipart")?
    } else {
        builder.body(p.body.clone()).context("build plain")?
    };

    Ok((msg.formatted(), message_id))
}
