//! Integration tests for the CalDAV layer against a local httpmock server.
//!
//! These tests bypass DNS-based service discovery (real iCloud) by going
//! through `Client::with_base_url_no_discovery` and injecting the calendar
//! home href via `set_calendar_home_for_tests`. CalDAV uses non-standard
//! HTTP methods (PROPFIND, REPORT), so the mocks are configured via
//! `when.matches(...)` rather than `when.method(...)`.

use http::Uri;
use httpmock::prelude::*;
use icloud_mcp::caldav::{Client, CreateEventParams};
use icloud_mcp::config::Config;

const FIND_CALENDARS: &str = include_str!("fixtures/find_calendars.xml");
const PROPS_WORK: &str = include_str!("fixtures/properties_work.xml");
const PROPS_PERSONAL: &str = include_str!("fixtures/properties_personal.xml");
const LIST_RESOURCES: &str = include_str!("fixtures/list_resources.xml");
const MULTIGET_EVENTS: &str = include_str!("fixtures/multiget_events.xml");
const MULTIGET_EMPTY: &str = include_str!("fixtures/multiget_empty.xml");

fn test_config() -> Config {
    Config {
        apple_id: "test@icloud.com".into(),
        app_password: "test-pass".into(),
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

#[tokio::test(flavor = "multi_thread")]
async fn list_calendars_returns_both_with_combined_propfind() {
    let server = MockServer::start_async().await;

    // FindCalendars (PROPFIND with Depth:1) on the calendar home.
    server.mock(|when, then| {
        when.matches(|req| req.method == "PROPFIND" && req.path == "/1234/calendars/");
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(FIND_CALENDARS);
    });

    // PROPFIND for properties on /1234/calendars/work/.
    server.mock(|when, then| {
        when.matches(|req| req.method == "PROPFIND" && req.path == "/1234/calendars/work/");
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(PROPS_WORK);
    });
    server.mock(|when, then| {
        when.matches(|req| req.method == "PROPFIND" && req.path == "/1234/calendars/personal/");
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
async fn list_events_filters_collection_and_returns_summaries() {
    let server = MockServer::start_async().await;

    // GetCalendarResources is also a REPORT to the same path. Register the
    // more specific (body-discriminated) matcher FIRST so httpmock picks it
    // for the multiget call instead of falling back to the LIST response.
    server.mock(|when, then| {
        when.matches(|req| {
            req.method == "REPORT"
                && req.path == "/1234/calendars/work/"
                && req
                    .body
                    .as_ref()
                    .map(|b| String::from_utf8_lossy(b).contains("calendar-multiget"))
                    .unwrap_or(false)
        });
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(MULTIGET_EVENTS);
    });
    // ListCalendarResources (REPORT calendar-query) - fallback for the
    // generic REPORT.
    server.mock(|when, then| {
        when.matches(|req| req.method == "REPORT" && req.path == "/1234/calendars/work/");
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(LIST_RESOURCES);
    });

    let client = build_client(&server.base_url());
    let (start, end) = parse_time_range("2026-05-14T00:00:00Z", "2026-05-15T00:00:00Z");
    let events = client
        .list_events("/1234/calendars/work/", start, end)
        .await
        .expect("list_events");

    // The collection self-row in LIST_RESOURCES must be filtered out by
    // resource_type.is_collection; we expect exactly the two .ics resources.
    assert_eq!(events.len(), 2);
    let titles: Vec<_> = events.iter().map(|e| e.summary.clone()).collect();
    assert!(titles.contains(&"Standup".to_string()));
    assert!(titles.contains(&"Design review".to_string()));
}

#[tokio::test(flavor = "multi_thread")]
async fn get_event_missing_resource_maps_to_not_found() {
    let server = MockServer::start_async().await;
    server.mock(|when, then| {
        when.matches(|req| req.method == "REPORT" && req.path == "/1234/calendars/work/");
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
    // would fail. This is httpmock 0.7's idiom for body inspection.
    let put_mock = server.mock(|when, then| {
        when.matches(|req| {
            if req.method != "PUT" {
                return false;
            }
            if !(req.path.starts_with("/1234/calendars/work/") && req.path.ends_with(".ics")) {
                return false;
            }
            let body = req
                .body
                .as_ref()
                .map(|b| String::from_utf8_lossy(b).into_owned())
                .unwrap_or_default();
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

    assert_eq!(put_mock.hits(), 1, "PUT should be called exactly once");
}

#[tokio::test(flavor = "multi_thread")]
async fn search_events_runs_across_multiple_calendars_in_parallel() {
    let server = MockServer::start_async().await;

    // 1) FindCalendars on home.
    server.mock(|when, then| {
        when.matches(|req| req.method == "PROPFIND" && req.path == "/1234/calendars/");
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(FIND_CALENDARS);
    });
    // 2) PROPFIND for properties (work + personal). list_calendars hits these
    //    before search dispatches per-calendar requests.
    server.mock(|when, then| {
        when.matches(|req| req.method == "PROPFIND" && req.path == "/1234/calendars/work/");
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(PROPS_WORK);
    });
    server.mock(|when, then| {
        when.matches(|req| req.method == "PROPFIND" && req.path == "/1234/calendars/personal/");
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(PROPS_PERSONAL);
    });

    // 3) REPORT (list + multiget) on each calendar. Both fan out concurrently.
    server.mock(|when, then| {
        when.matches(|req| {
            req.method == "REPORT"
                && req.path == "/1234/calendars/work/"
                && req
                    .body
                    .as_ref()
                    .map(|b| String::from_utf8_lossy(b).contains("calendar-multiget"))
                    .unwrap_or(false)
        });
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(MULTIGET_EVENTS);
    });
    server.mock(|when, then| {
        when.matches(|req| req.method == "REPORT" && req.path == "/1234/calendars/work/");
        then.status(207)
            .header("Content-Type", "application/xml; charset=utf-8")
            .body(LIST_RESOURCES);
    });
    server.mock(|when, then| {
        when.matches(|req| req.method == "REPORT" && req.path == "/1234/calendars/personal/");
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
