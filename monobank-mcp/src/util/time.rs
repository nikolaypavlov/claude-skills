//! Time helpers.
//!
//! Monobank's /personal/statement endpoint allows windows up to 31 days + 1
//! hour. We always pass exact 31-day windows to leave the +1h slack as a
//! safety buffer in case of clock skew. The last window is clamped to
//! "now" so we never query the future.

use chrono::{DateTime, Utc};

/// Window size used when chunking ranges. 31 days in seconds.
pub const CHUNK_SECONDS: i64 = 31 * 24 * 60 * 60;

/// Yield half-open windows [from, to) of `CHUNK_SECONDS` covering the
/// interval [start_ts, end_ts]. Returns empty when start_ts >= end_ts.
pub fn chunk_31d(start_ts: i64, end_ts: i64) -> Vec<(i64, i64)> {
    if start_ts >= end_ts {
        return Vec::new();
    }
    let mut chunks = Vec::new();
    let mut cursor = start_ts;
    while cursor < end_ts {
        let stop = (cursor + CHUNK_SECONDS).min(end_ts);
        chunks.push((cursor, stop));
        cursor = stop;
    }
    chunks
}

pub fn now_unix() -> i64 {
    Utc::now().timestamp()
}

pub fn parse_date_unix(s: &str) -> Result<i64, String> {
    if let Ok(ts) = s.parse::<i64>() {
        return Ok(ts);
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
        return Ok(dt.with_timezone(&Utc).timestamp());
    }
    // Accept YYYY-MM-DD by anchoring at 00:00:00 UTC.
    if let Ok(d) = chrono::NaiveDate::parse_from_str(s, "%Y-%m-%d") {
        if let Some(naive) = d.and_hms_opt(0, 0, 0) {
            return Ok(naive.and_utc().timestamp());
        }
    }
    Err(format!(
        "could not parse '{s}' as unix ts, RFC 3339, or YYYY-MM-DD"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chunk_31d_empty_when_range_inverted() {
        assert!(chunk_31d(100, 100).is_empty());
        assert!(chunk_31d(200, 100).is_empty());
    }

    #[test]
    fn chunk_31d_single_chunk_under_31_days() {
        let chunks = chunk_31d(0, 10);
        assert_eq!(chunks, vec![(0, 10)]);
    }

    #[test]
    fn chunk_31d_exactly_31_days_is_one_chunk() {
        let chunks = chunk_31d(0, CHUNK_SECONDS);
        assert_eq!(chunks, vec![(0, CHUNK_SECONDS)]);
    }

    #[test]
    fn chunk_31d_splits_long_range_into_consecutive_windows() {
        let chunks = chunk_31d(0, CHUNK_SECONDS * 2 + 100);
        assert_eq!(
            chunks,
            vec![
                (0, CHUNK_SECONDS),
                (CHUNK_SECONDS, CHUNK_SECONDS * 2),
                (CHUNK_SECONDS * 2, CHUNK_SECONDS * 2 + 100),
            ]
        );
    }

    #[test]
    fn parse_date_unix_accepts_three_forms() {
        let from_ts = parse_date_unix("1700000000").unwrap();
        let from_rfc = parse_date_unix("2023-11-14T22:13:20Z").unwrap();
        let from_date = parse_date_unix("2023-11-14").unwrap();
        assert_eq!(from_ts, 1700000000);
        assert_eq!(from_rfc, 1700000000);
        // YYYY-MM-DD anchors at midnight UTC, which is 22:13:20 earlier than the rfc one.
        assert_eq!(from_date, 1699920000);
    }

    #[test]
    fn parse_date_unix_rejects_garbage() {
        assert!(parse_date_unix("yesterday").is_err());
    }
}
