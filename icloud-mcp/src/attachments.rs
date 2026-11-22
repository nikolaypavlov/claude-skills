//! Attachment extraction and saving to local disk.
//!
//! Everything here is synchronous and free of IMAP state, so it runs inside
//! `spawn_blocking` and is tested without a server.
//!
//! ```text
//!   raw RFC 822 bytes (one UID FETCH BODY.PEEK[])
//!        |
//!        v
//!   mail-parser ---> extract()    one Attachment per attachment part,
//!        |                        `index` = position in that list
//!        v
//!   select()                      keep requested indexes (empty = all)
//!        |
//!        v
//!   safe_filename()               sender-supplied name -> one path component
//!        |
//!        v
//!   write_new()                   O_EXCL create inside dest_dir,
//!                                 "name-1.ext" on a name collision
//! ```
//!
//! Attachment names come from the sender and are untrusted. A name never
//! selects a directory, never overwrites an existing file and never follows
//! a symlink.

use std::borrow::Cow;
use std::fs::{self, OpenOptions};
use std::io::{ErrorKind, Write};
use std::path::{Path, PathBuf};

use mail_parser::decoders::base64::base64_decode;
use mail_parser::decoders::quoted_printable::quoted_printable_decode;
use mail_parser::{Encoding, Message, MessageParser, MessagePart, MimeHeaders, PartType};

use crate::error::DomainError;

/// Longest file name we generate, in bytes. APFS and ext4 allow 255; the
/// margin leaves room for the "-N" collision suffix.
const MAX_FILENAME_BYTES: usize = 200;
/// How many "-N" suffixes to try before giving up on a name.
const MAX_COLLISION_SUFFIX: u32 = 10_000;

/// One attachment of a parsed message.
#[derive(Debug, Clone)]
pub struct Attachment<'a> {
    /// Position in the message's attachment list, 0-based.
    pub index: usize,
    /// Name as the sender wrote it. Untrusted.
    pub filename: Option<String>,
    pub mime: String,
    pub bytes: Cow<'a, [u8]>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SavedAttachment {
    pub index: usize,
    /// Name as the sender wrote it; `path` holds the name used on disk.
    pub filename: Option<String>,
    pub mime: String,
    pub size_bytes: usize,
    pub path: String,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SaveResult {
    pub dest_dir: String,
    pub saved: Vec<SavedAttachment>,
    pub total_bytes: usize,
}

/// All attachments of `msg`, in the order mail-parser lists them.
pub fn extract<'a>(msg: &'a Message<'a>) -> Vec<Attachment<'a>> {
    msg.attachments()
        .enumerate()
        .map(|(index, part)| Attachment {
            index,
            filename: part.attachment_name().map(String::from),
            mime: mime_of(part),
            bytes: part_bytes(msg, part),
        })
        .collect()
}

/// Parse `raw`, then write the selected attachments into `dest_dir`.
///
/// `indexes` empty means all attachments. `dest_dir` must be absolute; it is
/// created when missing.
pub fn save_from_raw(
    raw: &[u8],
    dest_dir: &Path,
    indexes: &[usize],
) -> Result<SaveResult, DomainError> {
    let msg = MessageParser::default()
        .parse(raw)
        .ok_or_else(|| DomainError::permanent("failed to parse RFC 822"))?;
    let selected = select(extract(&msg), indexes)?;

    if !dest_dir.is_absolute() {
        return Err(DomainError::invalid(format!(
            "dest_dir must be an absolute path, got {}",
            dest_dir.display()
        )));
    }
    fs::create_dir_all(dest_dir).map_err(|e| {
        DomainError::invalid(format!(
            "cannot create dest_dir {}: {e}",
            dest_dir.display()
        ))
    })?;

    let mut saved = Vec::with_capacity(selected.len());
    let mut total_bytes = 0;
    for att in selected {
        let name = safe_filename(att.filename.as_deref(), att.index, &att.mime);
        let path = write_new(dest_dir, &name, &att.bytes).map_err(|e| {
            DomainError::permanent(format!(
                "write attachment {} into {}: {e} ({} file(s) written before the failure)",
                att.index,
                dest_dir.display(),
                saved.len()
            ))
        })?;
        total_bytes += att.bytes.len();
        saved.push(SavedAttachment {
            index: att.index,
            filename: att.filename,
            mime: att.mime,
            size_bytes: att.bytes.len(),
            path: path.to_string_lossy().into_owned(),
        });
    }

    Ok(SaveResult {
        dest_dir: dest_dir.to_string_lossy().into_owned(),
        saved,
        total_bytes,
    })
}

/// Keep the attachments named by `indexes`, in message order. Empty
/// `indexes` keeps all. An index the message does not have is an error, so
/// a caller never gets a silent partial save.
fn select<'a>(
    all: Vec<Attachment<'a>>,
    indexes: &[usize],
) -> Result<Vec<Attachment<'a>>, DomainError> {
    if all.is_empty() {
        return Err(DomainError::not_found("message has no attachments"));
    }
    if indexes.is_empty() {
        return Ok(all);
    }
    if let Some(bad) = indexes.iter().find(|i| **i >= all.len()) {
        return Err(DomainError::invalid(format!(
            "attachment index {bad} out of range: message has {} attachment(s), indexes 0..={}",
            all.len(),
            all.len() - 1
        )));
    }
    Ok(all
        .into_iter()
        .filter(|a| indexes.contains(&a.index))
        .collect())
}

fn mime_of(part: &MessagePart<'_>) -> String {
    part.content_type()
        .map(|ct| match ct.subtype() {
            Some(s) => format!("{}/{s}", ct.ctype()),
            None => ct.ctype().to_string(),
        })
        .unwrap_or_else(|| "application/octet-stream".to_string())
}

/// Bytes of one part as the sender attached them.
///
/// mail-parser transcodes `text/*` parts to UTF-8 (lossy when no charset is
/// declared), which would corrupt a Windows-1251 CSV. For text parts we
/// therefore decode the transfer encoding ourselves from the raw message
/// span, and fall back to the transcoded text only if that fails.
fn part_bytes<'a>(msg: &'a Message<'a>, part: &'a MessagePart<'a>) -> Cow<'a, [u8]> {
    if !matches!(part.body, PartType::Text(_) | PartType::Html(_)) {
        return Cow::Borrowed(part.contents());
    }
    let raw = msg.raw_message();
    let span = raw.get(part.offset_body as usize..part.offset_end as usize);
    let decoded = span.and_then(|span| match part.encoding {
        Encoding::None => Some(Cow::Borrowed(span)),
        Encoding::Base64 => base64_decode(span).map(Cow::Owned),
        Encoding::QuotedPrintable => quoted_printable_decode(span).map(Cow::Owned),
    });
    decoded.unwrap_or_else(|| Cow::Borrowed(part.contents()))
}

/// Turn a sender-supplied attachment name into a single safe path component.
///
/// - only the last component is kept (both `/` and `\` separate)
/// - control characters and NUL are dropped
/// - leading dots are dropped, so no hidden file and no `.` / `..`
/// - the result is capped at [`MAX_FILENAME_BYTES`]
/// - an empty result becomes `attachment-<index>.<ext>`
pub fn safe_filename(name: Option<&str>, index: usize, mime: &str) -> String {
    let base = name
        .and_then(|n| n.rsplit(['/', '\\']).next())
        .unwrap_or("");
    let cleaned: String = base.chars().filter(|c| !c.is_control()).collect();
    let cleaned = cleaned.trim().trim_start_matches('.').trim();
    if cleaned.is_empty() {
        return format!("attachment-{index}.{}", extension_for(mime));
    }
    truncate_keeping_extension(cleaned, MAX_FILENAME_BYTES)
}

fn extension_for(mime: &str) -> &'static str {
    match mime.to_ascii_lowercase().as_str() {
        "text/plain" => "txt",
        "text/csv" => "csv",
        "text/html" => "html",
        "text/calendar" => "ics",
        "application/pdf" => "pdf",
        "application/json" => "json",
        "application/zip" => "zip",
        "image/png" => "png",
        "image/jpeg" => "jpg",
        "message/rfc822" => "eml",
        _ => "bin",
    }
}

fn split_extension(name: &str) -> (&str, &str) {
    match name.rfind('.') {
        Some(pos) if pos > 0 => name.split_at(pos),
        _ => (name, ""),
    }
}

fn truncate_keeping_extension(name: &str, max_bytes: usize) -> String {
    if name.len() <= max_bytes {
        return name.to_string();
    }
    let (stem, ext) = split_extension(name);
    // An over-long "extension" is not an extension; cut the whole name.
    let (stem, ext) = if ext.len() > 16 {
        (name, "")
    } else {
        (stem, ext)
    };
    let mut cut = max_bytes - ext.len();
    while !stem.is_char_boundary(cut) {
        cut -= 1;
    }
    format!("{}{ext}", &stem[..cut])
}

/// Create a new file named `name` in `dir` and write `bytes` to it.
///
/// `create_new` maps to `O_CREAT | O_EXCL`: an existing file is never
/// overwritten and a symlink at that name is never followed. On a collision
/// the name gets a `-N` suffix before the extension.
fn write_new(dir: &Path, name: &str, bytes: &[u8]) -> std::io::Result<PathBuf> {
    let (stem, ext) = split_extension(name);
    for n in 0..=MAX_COLLISION_SUFFIX {
        let candidate = if n == 0 {
            name.to_string()
        } else {
            format!("{stem}-{n}{ext}")
        };
        let path = dir.join(candidate);
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut file) => {
                file.write_all(bytes)?;
                return Ok(path);
            }
            Err(e) if e.kind() == ErrorKind::AlreadyExists => {}
            Err(e) => return Err(e),
        }
    }
    Err(std::io::Error::new(
        ErrorKind::AlreadyExists,
        format!("no free file name for {name:?}"),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    /// A fresh directory under the system temp dir, removed on drop.
    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("icloud-mcp-test-{}", Uuid::new_v4()));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    /// One MIME part: headers, then the already-encoded body.
    struct Part {
        headers: &'static str,
        body: Vec<u8>,
    }

    fn part(headers: &'static str, body: &[u8]) -> Part {
        Part {
            headers,
            body: body.to_vec(),
        }
    }

    /// multipart/mixed message: a plain-text body followed by `parts`.
    fn message(parts: &[Part]) -> Vec<u8> {
        let mut raw = Vec::new();
        raw.extend_from_slice(
            b"From: a@example.com\r\nTo: b@example.com\r\nSubject: t\r\n\
              MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=\"XX\"\r\n\r\n\
              --XX\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nbody text\r\n",
        );
        for p in parts {
            raw.extend_from_slice(b"--XX\r\n");
            raw.extend_from_slice(p.headers.as_bytes());
            raw.extend_from_slice(b"\r\n\r\n");
            raw.extend_from_slice(&p.body);
            raw.extend_from_slice(b"\r\n");
        }
        raw.extend_from_slice(b"--XX--\r\n");
        raw
    }

    const CSV_7BIT: &str = "Content-Type: text/csv; name=\"a.csv\"\r\n\
        Content-Disposition: attachment; filename=\"a.csv\"";

    #[test]
    fn saves_all_attachments_with_exact_bytes() {
        let csv = b"OBJECT_NAME,EPOCH\r\nSTARLINK-1,2026-11-19T00:00:00\r\n";
        let raw = message(&[
            part(CSV_7BIT, csv),
            part(
                "Content-Type: application/octet-stream\r\n\
                 Content-Transfer-Encoding: base64\r\n\
                 Content-Disposition: attachment; filename=\"b.bin\"",
                b"AAEC/w==",
            ),
        ]);
        let dir = TempDir::new();

        let res = save_from_raw(&raw, &dir.0, &[]).unwrap();

        assert_eq!(res.saved.len(), 2);
        assert_eq!(res.saved[0].index, 0);
        assert_eq!(res.saved[0].mime, "text/csv");
        assert_eq!(res.saved[0].size_bytes, csv.len());
        assert_eq!(fs::read(dir.0.join("a.csv")).unwrap(), csv);
        assert_eq!(fs::read(dir.0.join("b.bin")).unwrap(), [0, 1, 2, 0xff]);
        assert_eq!(res.total_bytes, csv.len() + 4);
    }

    #[test]
    fn text_attachment_keeps_non_utf8_bytes() {
        // "Привіт" in Windows-1251 with no charset declared: mail-parser's
        // own text decoding would replace every byte with U+FFFD.
        let cp1251: &[u8] = &[0xcf, 0xf0, 0xe8, 0xe2, 0xb3, 0xf2];
        let raw = message(&[
            part(
                "Content-Type: text/csv; name=\"raw.csv\"\r\n\
                 Content-Transfer-Encoding: 8bit\r\n\
                 Content-Disposition: attachment; filename=\"raw.csv\"",
                cp1251,
            ),
            part(
                "Content-Type: text/csv; charset=windows-1251; name=\"b64.csv\"\r\n\
                 Content-Transfer-Encoding: base64\r\n\
                 Content-Disposition: attachment; filename=\"b64.csv\"",
                b"z/Do4rPy",
            ),
            part(
                "Content-Type: text/csv; charset=windows-1251; name=\"qp.csv\"\r\n\
                 Content-Transfer-Encoding: quoted-printable\r\n\
                 Content-Disposition: attachment; filename=\"qp.csv\"",
                b"=CF=F0=E8=E2=B3=F2",
            ),
        ]);
        let dir = TempDir::new();

        save_from_raw(&raw, &dir.0, &[]).unwrap();

        for name in ["raw.csv", "b64.csv", "qp.csv"] {
            assert_eq!(fs::read(dir.0.join(name)).unwrap(), cp1251, "{name}");
        }
    }

    #[test]
    fn wrapped_base64_and_soft_broken_qp_keep_non_utf8_bytes() {
        // 60 lines of Windows-1251 text, so base64 wraps at 76 columns and
        // quoted-printable needs soft line breaks, like real mail.
        let line: &[u8] = &[0xcf, 0xf0, 0xe8, 0xe2, 0xb3, 0xf2, b',', b'1', b'\r', b'\n'];
        let payload = line.repeat(60);

        let b64_alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        let mut b64 = Vec::new();
        for (i, chunk) in payload.chunks(3).enumerate() {
            if i > 0 && i % 19 == 0 {
                b64.extend_from_slice(b"\r\n");
            }
            let n = u32::from(chunk[0]) << 16
                | u32::from(*chunk.get(1).unwrap_or(&0)) << 8
                | u32::from(*chunk.get(2).unwrap_or(&0));
            for (k, shift) in [18, 12, 6, 0].into_iter().enumerate() {
                if k <= chunk.len() {
                    b64.push(b64_alphabet[(n >> shift) as usize & 63]);
                } else {
                    b64.push(b'=');
                }
            }
        }

        let mut qp = Vec::new();
        let mut col = 0;
        for &b in &payload {
            if col >= 70 {
                qp.extend_from_slice(b"=\r\n");
                col = 0;
            }
            if b == b'\r' || b == b'\n' || b >= 0x80 {
                qp.extend_from_slice(format!("={b:02X}").as_bytes());
                col += 3;
            } else {
                qp.push(b);
                col += 1;
            }
        }

        let raw = message(&[
            part(
                "Content-Type: text/csv; charset=windows-1251; name=\"b64.csv\"\r\n\
                 Content-Transfer-Encoding: base64\r\n\
                 Content-Disposition: attachment; filename=\"b64.csv\"",
                &b64,
            ),
            part(
                "Content-Type: text/csv; name=\"qp.csv\"\r\n\
                 Content-Transfer-Encoding: quoted-printable\r\n\
                 Content-Disposition: attachment; filename=\"qp.csv\"",
                &qp,
            ),
        ]);
        let dir = TempDir::new();

        save_from_raw(&raw, &dir.0, &[]).unwrap();

        for name in ["b64.csv", "qp.csv"] {
            assert_eq!(fs::read(dir.0.join(name)).unwrap(), payload, "{name}");
        }
    }

    #[test]
    fn indexes_select_a_subset() {
        let raw = message(&[
            part(CSV_7BIT, b"one"),
            part(
                "Content-Type: text/csv\r\n\
                 Content-Disposition: attachment; filename=\"b.csv\"",
                b"two",
            ),
        ]);
        let dir = TempDir::new();

        let res = save_from_raw(&raw, &dir.0, &[1]).unwrap();

        assert_eq!(res.saved.len(), 1);
        assert_eq!(res.saved[0].index, 1);
        assert!(!dir.0.join("a.csv").exists());
        assert_eq!(fs::read(dir.0.join("b.csv")).unwrap(), b"two");
    }

    #[test]
    fn index_out_of_range_is_invalid_input_and_writes_nothing() {
        let raw = message(&[part(CSV_7BIT, b"one")]);
        let dir = TempDir::new();

        let err = save_from_raw(&raw, &dir.0, &[0, 3]).unwrap_err();

        assert!(matches!(err, DomainError::InvalidInput(_)), "{err:?}");
        assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 0);
    }

    #[test]
    fn message_without_attachments_is_not_found() {
        let raw = message(&[]);
        let dir = TempDir::new();
        let err = save_from_raw(&raw, &dir.0, &[]).unwrap_err();
        assert!(matches!(err, DomainError::NotFound(_)), "{err:?}");
    }

    #[test]
    fn relative_dest_dir_is_rejected() {
        let raw = message(&[part(CSV_7BIT, b"one")]);
        let err = save_from_raw(&raw, Path::new("relative/dir"), &[]).unwrap_err();
        assert!(matches!(err, DomainError::InvalidInput(_)), "{err:?}");
    }

    #[test]
    fn missing_dest_dir_is_created() {
        let raw = message(&[part(CSV_7BIT, b"one")]);
        let dir = TempDir::new();
        let nested = dir.0.join("x").join("y");

        save_from_raw(&raw, &nested, &[]).unwrap();

        assert_eq!(fs::read(nested.join("a.csv")).unwrap(), b"one");
    }

    #[test]
    fn traversal_name_stays_inside_dest_dir() {
        let raw = message(&[part(
            "Content-Type: application/octet-stream\r\n\
             Content-Disposition: attachment; filename=\"../../evil.sh\"",
            b"x",
        )]);
        let dir = TempDir::new();
        let dest = dir.0.join("inner");

        let res = save_from_raw(&raw, &dest, &[]).unwrap();

        assert_eq!(Path::new(&res.saved[0].path), dest.join("evil.sh"));
        assert!(!dir.0.join("evil.sh").exists());
    }

    #[test]
    fn existing_file_and_duplicate_names_are_not_overwritten() {
        let raw = message(&[part(CSV_7BIT, b"new-1"), part(CSV_7BIT, b"new-2")]);
        let dir = TempDir::new();
        fs::write(dir.0.join("a.csv"), b"old").unwrap();

        let res = save_from_raw(&raw, &dir.0, &[]).unwrap();

        assert_eq!(fs::read(dir.0.join("a.csv")).unwrap(), b"old");
        assert_eq!(fs::read(dir.0.join("a-1.csv")).unwrap(), b"new-1");
        assert_eq!(fs::read(dir.0.join("a-2.csv")).unwrap(), b"new-2");
        assert!(res.saved[0].path.ends_with("a-1.csv"));
        assert_eq!(res.saved[0].filename.as_deref(), Some("a.csv"));
    }

    #[cfg(unix)]
    #[test]
    fn symlink_at_target_name_is_not_followed() {
        let raw = message(&[part(CSV_7BIT, b"new")]);
        let dir = TempDir::new();
        let outside = dir.0.join("outside.txt");
        fs::write(&outside, b"keep").unwrap();
        let dest = dir.0.join("dest");
        fs::create_dir(&dest).unwrap();
        std::os::unix::fs::symlink(&outside, dest.join("a.csv")).unwrap();

        save_from_raw(&raw, &dest, &[]).unwrap();

        assert_eq!(fs::read(&outside).unwrap(), b"keep");
        assert_eq!(fs::read(dest.join("a-1.csv")).unwrap(), b"new");
    }

    #[test]
    fn nameless_attachment_gets_generated_name() {
        let raw = message(&[part(
            "Content-Type: application/pdf\r\nContent-Disposition: attachment",
            b"%PDF",
        )]);
        let dir = TempDir::new();

        let res = save_from_raw(&raw, &dir.0, &[]).unwrap();

        assert_eq!(res.saved[0].filename, None);
        assert_eq!(fs::read(dir.0.join("attachment-0.pdf")).unwrap(), b"%PDF");
    }

    #[test]
    fn safe_filename_keeps_ordinary_names() {
        assert_eq!(
            safe_filename(Some("sat000048093.csv"), 0, "text/csv"),
            "sat000048093.csv"
        );
        assert_eq!(
            safe_filename(Some("Звіт 2026.xlsx"), 0, "x/y"),
            "Звіт 2026.xlsx"
        );
    }

    #[test]
    fn safe_filename_strips_directories() {
        assert_eq!(safe_filename(Some("../../etc/passwd"), 0, "x/y"), "passwd");
        assert_eq!(safe_filename(Some("/abs/path/f.txt"), 0, "x/y"), "f.txt");
        assert_eq!(
            safe_filename(Some("C:\\Users\\a\\f.txt"), 0, "x/y"),
            "f.txt"
        );
    }

    #[test]
    fn safe_filename_falls_back_when_nothing_usable_remains() {
        assert_eq!(safe_filename(None, 3, "text/csv"), "attachment-3.csv");
        assert_eq!(safe_filename(Some(""), 3, "text/csv"), "attachment-3.csv");
        assert_eq!(safe_filename(Some(".."), 3, "x/y"), "attachment-3.bin");
        assert_eq!(safe_filename(Some("dir/"), 3, "x/y"), "attachment-3.bin");
        assert_eq!(
            safe_filename(Some(" \u{0}\n "), 3, "x/y"),
            "attachment-3.bin"
        );
    }

    #[test]
    fn safe_filename_drops_leading_dots_and_control_chars() {
        assert_eq!(safe_filename(Some(".zshrc"), 0, "x/y"), "zshrc");
        assert_eq!(safe_filename(Some("a\u{0}b\r\n.txt"), 0, "x/y"), "ab.txt");
    }

    #[test]
    fn safe_filename_truncates_on_char_boundary_and_keeps_extension() {
        let long = format!("{}.csv", "ї".repeat(300));
        let out = safe_filename(Some(&long), 0, "text/csv");
        assert!(out.len() <= MAX_FILENAME_BYTES, "{}", out.len());
        assert!(out.ends_with(".csv"));
        assert!(out.starts_with('ї'));
    }
}
