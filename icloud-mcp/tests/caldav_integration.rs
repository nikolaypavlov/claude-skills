//! Integration tests for the CalDAV layer against a local httpmock server.
//!
//! These tests bypass DNS-based service discovery (real iCloud) by going
//! through `Client::with_base_url_no_discovery` and injecting the calendar
//! home href via `set_calendar_home_for_tests`. CalDAV uses non-standard
//! HTTP methods (PROPFIND, REPORT), so the mocks are configured via
//! `when.is_true(...)` rather than `when.method(...)`.

use http::Uri;
use httpmock::prelude::*;
use icloud_mcp::caldav::{Client, CreateEventParams};
use icloud_mcp::config::{Config, CredentialSource};

const FIND_CALENDARS: &str = include_str!("fixtures/find_calendars.xml");
const PROPS_WORK: &str = include_str!("fixtures/properties_work.xml");
const PROPS_PERSONAL: &str = include_str!("fixtures/properties_personal.xml");
const EXPANDED_EVENTS: &str = include_str!("fixtures/multiget_events.xml");
const EXPANDED_RECURRING: &str = include_str!("fixtures/expanded_recurring.xml");
const MULTIGET_EMPTY: &str = include_str!("fixtures/multiget_empty.xml");

fn test_config() -> Config {
    Config {
        apple_id: "test@icloud.com".into(),
        app_password: "test-pass".into(),
        source: CredentialSource::Env,
    }
}

fn build_client(base: &str) -> Client {
    let uri: Uri = base.parse().expect("base url");
    let client = Client::with_base_url_no_discovery(uri, &test_config()).expect("client");
    client.set_calendar_home_for_tests("/1234/calendars/".to_string());
    client
}

fn parse_time_range(
    start: &str,
    end: &str,
) -> (chrono::DateTime<chrono::Utc>, chrono::DateTime<chrono::Utc>) {
    (
        chrono::DateTime::parse_from_rfc3339(start)
            .unwrap()
            .with_timezone(&chrono::Utc),
        chrono::DateTime::parse_from_rfc3339(end)
            .unwrap()
            .with_timezone(&chrono::Utc),
    )
}

/// httpmock 0.8 exposes request data through accessor methods; we wrap the
/// "is the method M and path P" check that every test below uses.
fn method_and_path(method: &str, path: &str) -> impl Fn(&httpmock::HttpMockRequest) -> bool {
    let method = method.to_string();
    let path = path.to_string();
    move |req| req.method_str() == method && req.uri().path() == path
}

fn body_contains(req: &httpmock::HttpMockRequest, needle: &str) -> bool {
    let body = String::from_utf8_lossy(req.body_ref());
    body.contains(needle)
}

#[tokio::test(flavor = "multi_thread")]
async fn list_calendars_returns_both_with_combined_propfind() {
    let server = MockServer::start_async().await;

    // FindCalendars (PROPFIND with Depth:1) on the calendar home.
    server.mock(|when, then| {
        when.is_true(method_and_path("PROPFIND", "/1234/calendars/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(FIND_CALENDARS);
    });

    // PROPFIND for properties on /1234/calendars/work/.
    server.mock(|when, then| {
        when.is_true(method_and_path("PROPFIND", "/1234/calendars/work/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(PROPS_WORK);
    });
    server.mock(|when, then| {
        when.is_true(method_and_path("PROPFIND", "/1234/calendars/personal/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(PROPS_PERSONAL);
    });

    let client = build_client(&server.base_url());
    let cals = client.list_calendars().await.expect("list_calendars");
    assert_eq!(cals.len(), 2);

    let work = cals
        .iter()
        .find(|c| c.id == "/1234/calendars/work/")
        .expect("work calendar");
    assert_eq!(work.display_name, "Work");
    assert_eq!(work.color.as_deref(), Some("#FF5733"));

    let personal = cals
        .iter()
        .find(|c| c.id == "/1234/calendars/personal/")
        .expect("personal calendar");
    assert_eq!(personal.display_name, "Personal");
    assert_eq!(personal.color.as_deref(), Some("#33A1FF"));
}

#[tokio::test(flavor = "multi_thread")]
async fn list_events_uses_calendar_query_with_expand() {
    let server = MockServer::start_async().await;

    // list_events now issues a single REPORT carrying a `calendar-query` body
    // with `<C:expand>`. The server returns one VEVENT per occurrence inside
    // each response's calendar-data.
    let expand_mock = server.mock(|when, then| {
        when.is_true(|req| {
            req.method_str() == "REPORT"
                && req.uri().path() == "/1234/calendars/work/"
                && body_contains(req, "calendar-query")
                && body_contains(req, "<C:expand")
        });
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(EXPANDED_EVENTS);
    });

    let client = build_client(&server.base_url());
    let (start, end) = parse_time_range("2026-05-14T00:00:00Z", "2026-05-15T00:00:00Z");
    let events = client
        .list_events("/1234/calendars/work/", start, end)
        .await
        .expect("list_events");

    assert_eq!(expand_mock.calls(), 1, "exactly one REPORT expected");
    assert_eq!(events.len(), 2);
    let titles: Vec<_> = events.iter().map(|e| e.summary.clone()).collect();
    assert!(titles.contains(&"Standup".to_string()));
    assert!(titles.contains(&"Design review".to_string()));
}

#[tokio::test(flavor = "multi_thread")]
async fn list_events_returns_one_summary_per_recurring_occurrence() {
    let server = MockServer::start_async().await;

    server.mock(|when, then| {
        when.is_true(|req| {
            req.method_str() == "REPORT" && req.uri().path() == "/1234/calendars/work/"
        });
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(EXPANDED_RECURRING);
    });

    let client = build_client(&server.base_url());
    let (start, end) = parse_time_range("2026-05-14T00:00:00Z", "2026-06-01T00:00:00Z");
    let events = client
        .list_events("/1234/calendars/work/", start, end)
        .await
        .expect("list_events");

    // Three expanded occurrences of one master "Weekly sync" event.
    assert_eq!(events.len(), 3);
    let starts: Vec<&str> = events.iter().map(|e| e.start.as_str()).collect();
    assert!(starts.iter().any(|s| s.starts_with("2026-05-14T09:00:00")));
    assert!(starts.iter().any(|s| s.starts_with("2026-05-21T09:00:00")));
    assert!(starts.iter().any(|s| s.starts_with("2026-05-28T09:00:00")));
    for e in &events {
        assert_eq!(e.uid, "weekly-uid");
        assert_eq!(e.href, "/1234/calendars/work/weekly.ics");
        assert!(
            e.instance_id.is_some(),
            "expanded occurrence must carry RECURRENCE-ID"
        );
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn get_event_missing_resource_maps_to_not_found() {
    let server = MockServer::start_async().await;
    server.mock(|when, then| {
        when.is_true(method_and_path("REPORT", "/1234/calendars/work/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(MULTIGET_EMPTY);
    });

    let client = build_client(&server.base_url());
    let err = client
        .get_event("/1234/calendars/work/", "missing-uid")
        .await
        .expect_err("should be NotFound");
    let s = format!("{err}");
    assert!(s.contains("not found"), "unexpected error: {s}");
}

#[tokio::test(flavor = "multi_thread")]
async fn create_event_puts_full_vevent_with_method_request() {
    use chrono::TimeZone;

    let server = MockServer::start_async().await;
    // Body assertions live inside the matcher: if the PUT body lacks any of
    // the required iCalendar properties the mock will not match and the call
    // would fail.
    let put_mock = server.mock(|when, then| {
        when.is_true(|req| {
            if req.method_str() != "PUT" {
                return false;
            }
            let path = req.uri().path().to_string();
            if !(path.starts_with("/1234/calendars/work/") && path.ends_with(".ics")) {
                return false;
            }
            let body = String::from_utf8_lossy(req.body_ref());
            let body = body.replace("\r\n ", "").replace("\n ", "");
            body.contains("BEGIN:VEVENT")
                && body.contains("DTSTAMP:")
                && body.contains("METHOD:REQUEST")
                && body.contains("RSVP=TRUE")
                && body.contains("PARTSTAT=NEEDS-ACTION")
                && body.contains("mailto:alice@example.com")
        });
        then.status(201).header("ETag", "\"created-1\"");
    });

    let client = build_client(&server.base_url());
    let p = CreateEventParams {
        title: "Standup".into(),
        start: chrono::Utc.with_ymd_and_hms(2026, 5, 14, 9, 0, 0).unwrap(),
        end: chrono::Utc.with_ymd_and_hms(2026, 5, 14, 9, 30, 0).unwrap(),
        description: None,
        location: None,
        attendees: vec!["alice@example.com".into()],
        organizer: "me@example.com".into(),
    };

    let summary = client
        .create_event("/1234/calendars/work/", p)
        .await
        .expect("create_event");
    assert_eq!(summary.etag.as_deref(), Some("\"created-1\""));
    assert!(summary.href.ends_with(".ics"));
    assert_eq!(summary.summary, "Standup");

    assert_eq!(put_mock.calls(), 1, "PUT should be called exactly once");
}

#[tokio::test(flavor = "multi_thread")]
async fn search_events_runs_across_multiple_calendars_in_parallel() {
    let server = MockServer::start_async().await;

    // 1) FindCalendars on home.
    server.mock(|when, then| {
        when.is_true(method_and_path("PROPFIND", "/1234/calendars/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(FIND_CALENDARS);
    });
    // 2) PROPFIND for properties (work + personal). list_calendars hits these
    //    before search dispatches per-calendar requests.
    server.mock(|when, then| {
        when.is_true(method_and_path("PROPFIND", "/1234/calendars/work/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(PROPS_WORK);
    });
    server.mock(|when, then| {
        when.is_true(method_and_path("PROPFIND", "/1234/calendars/personal/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(PROPS_PERSONAL);
    });

    // 3) Single calendar-query REPORT per calendar (with <C:expand>).
    server.mock(|when, then| {
        when.is_true(|req| {
            req.method_str() == "REPORT" && req.uri().path() == "/1234/calendars/work/"
        });
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(EXPANDED_EVENTS);
    });
    server.mock(|when, then| {
        when.is_true(method_and_path("REPORT", "/1234/calendars/personal/"));
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(MULTIGET_EMPTY);
    });

    let client = build_client(&server.base_url());
    let (start, end) = parse_time_range("2026-05-14T00:00:00Z", "2026-05-15T00:00:00Z");
    let hits = client
        .search_events("standup", start, end, None)
        .await
        .expect("search_events");
    // Only the work calendar has a "Standup" entry; personal is empty.
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].summary, "Standup");
}
