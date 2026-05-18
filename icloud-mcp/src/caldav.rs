//! CalDAV client wrapper around [`libdav`] plus a raw hyper path for the one
//! request libdav cannot express - `calendar-query` with `<C:expand>`.
//!
//! Flow:
//!     1. `Client::new` builds a hyper-rustls https client, wraps it with Basic auth
//!        (tower_http), then bootstraps a [`CalDavClient`] via DNS service discovery.
//!     2. `list_calendars` finds the principal -> calendar-home-set -> collections,
//!        then queries displayname + colour for each (one combined PROPFIND each).
//!     3. `list_events` issues a single `REPORT` with a `calendar-query` body
//!        containing `<C:expand start=... end=.../>`. iCloud returns one VEVENT
//!        per occurrence (RRULE stripped, EXDATE applied, RECURRENCE-ID overrides
//!        substituted). We parse the multistatus with `quick-xml` and emit one
//!        `EventSummary` per VEVENT, preserving RECURRENCE-ID in `instance_id`.
//!     4. `search_events` fans out across calendars in parallel.
//!     5. `create_event` builds a VEVENT with `icalendar` (full DTSTAMP+METHOD+
//!        ATTENDEE params) and PUTs it.

use bytes::Bytes;
use chrono::{DateTime, Utc};
use futures_util::future::join_all;
use http::{Request, Uri};
use http_body_util::{BodyExt, Full};
use hyper_rustls::HttpsConnectorBuilder;
use hyper_util::client::legacy::{connect::HttpConnector, Client as HyperClient};
use hyper_util::rt::TokioExecutor;
use icalendar::{
    Calendar as ICalendar, CalendarComponent, Component, Event as ICalEvent, EventLike, Property,
};
use libdav::caldav::{FindCalendarHomeSet, FindCalendars, GetCalendarResources};
use libdav::dav::{GetProperties, PutResource, WebDavClient};
use libdav::{names, CalDavClient};
use tokio::sync::OnceCell;
use tower::ServiceExt;
use tower_http::auth::AddAuthorization;
use uuid::Uuid;

use crate::config::{Config, CALDAV_BASE};
use crate::error::DomainError;
use crate::timeout::{with_timeout, CALDAV_REQUEST};

type AuthClient =
    AddAuthorization<HyperClient<hyper_rustls::HttpsConnector<HttpConnector>, String>>;

/// Raw HTTP client used for the `calendar-query` REPORT with `<C:expand>`.
///
/// libdav's typed `ListCalendarResources` does not expose `<C:expand>` (it
/// would return the master event with its RRULE intact - so callers would see
/// the original DTSTART rather than each occurrence in their query window).
/// We send the REPORT ourselves and let iCloud expand RRULE / apply EXDATE
/// / fold RECURRENCE-ID overrides server-side, then parse the resulting
/// multistatus.
type RawClient =
    AddAuthorization<HyperClient<hyper_rustls::HttpsConnector<HttpConnector>, Full<Bytes>>>;

fn build_webdav(base_url: Uri, config: &Config) -> Result<WebDavClient<AuthClient>, DomainError> {
    let connector = HttpsConnectorBuilder::new()
        .with_native_roots()
        .map_err(|e| DomainError::permanent(format!("loading native TLS roots: {e}")))?
        .https_or_http()
        .enable_http1()
        .build();
    let hyper_client = HyperClient::builder(TokioExecutor::new()).build(connector);
    let auth_client = AddAuthorization::basic(hyper_client, &config.apple_id, &config.app_password);
    Ok(WebDavClient::new(base_url, auth_client))
}

fn build_raw_client(config: &Config) -> Result<RawClient, DomainError> {
    let connector = HttpsConnectorBuilder::new()
        .with_native_roots()
        .map_err(|e| DomainError::permanent(format!("loading native TLS roots: {e}")))?
        .https_or_http()
        .enable_http1()
        .build();
    let hyper_client: HyperClient<_, Full<Bytes>> =
        HyperClient::builder(TokioExecutor::new()).build(connector);
    Ok(AddAuthorization::basic(
        hyper_client,
        &config.apple_id,
        &config.app_password,
    ))
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct CalendarInfo {
    pub id: String,
    pub display_name: String,
    pub color: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct EventSummary {
    pub uid: String,
    pub href: String,
    pub summary: String,
    pub start: String,
    pub end: String,
    pub location: Option<String>,
    pub all_day: bool,
    pub etag: Option<String>,
    /// For occurrences of a recurring event, the RECURRENCE-ID identifying
    /// the specific instance returned by server-side `<C:expand>`. `None` for
    /// single events and for entries returned via the legacy non-expanded
    /// path.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub instance_id: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct EventDetail {
    pub uid: String,
    pub href: String,
    pub summary: String,
    pub description: Option<String>,
    pub location: Option<String>,
    pub start: String,
    pub end: String,
    pub all_day: bool,
    pub status: Option<String>,
    pub organizer: Option<String>,
    pub attendees: Vec<String>,
    pub etag: Option<String>,
    pub ical: String,
}

#[derive(Debug, Clone)]
pub struct CreateEventParams {
    pub title: String,
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub description: Option<String>,
    pub location: Option<String>,
    pub attendees: Vec<String>,
    pub organizer: String,
}

pub struct Client {
    inner: CalDavClient<AuthClient>,
    raw: RawClient,
    base_url: Uri,
    home: OnceCell<String>,
}

impl Client {
    pub async fn new(config: &Config) -> Result<Self, DomainError> {
        let base_url: Uri = CALDAV_BASE.parse().map_err(|e: http::uri::InvalidUri| {
            DomainError::permanent(format!("CALDAV_BASE: {e}"))
        })?;
        let webdav = build_webdav(base_url.clone(), config)?;
        let raw = build_raw_client(config)?;
        let caldav = with_timeout("CalDAV service discovery", CALDAV_REQUEST, async {
            CalDavClient::bootstrap_via_service_discovery(webdav)
                .await
                .map_err(|e| DomainError::transient(format!("CalDAV service discovery: {e}")))
        })
        .await?;
        Ok(Self {
            inner: caldav,
            raw,
            base_url,
            home: OnceCell::new(),
        })
    }

    /// Build a client against an explicit base URL without service discovery.
    /// Used by integration tests against a local httpmock instance and by any
    /// caller that already knows the exact CalDAV root path.
    pub fn with_base_url_no_discovery(base_url: Uri, config: &Config) -> Result<Self, DomainError> {
        let webdav = build_webdav(base_url.clone(), config)?;
        let raw = build_raw_client(config)?;
        Ok(Self {
            inner: CalDavClient::new(webdav),
            raw,
            base_url,
            home: OnceCell::new(),
        })
    }

    /// Inject an already-discovered calendar-home-set href. Tests use this so
    /// they do not need to mock the principal -> home-set dance.
    pub fn set_calendar_home_for_tests(&self, href: String) {
        let _ = self.home.set(href);
    }

    async fn calendar_home(&self) -> Result<String, DomainError> {
        self.home
            .get_or_try_init(|| async {
                let principal =
                    with_timeout("find_current_user_principal", CALDAV_REQUEST, async {
                        self.inner
                            .find_current_user_principal()
                            .await
                            .map_err(|e| {
                                DomainError::permanent(format!("find_current_user_principal: {e}"))
                            })?
                            .ok_or_else(|| {
                                DomainError::permanent(
                                    "server did not return a current-user-principal",
                                )
                            })
                    })
                    .await?;
                let resp = with_timeout("FindCalendarHomeSet", CALDAV_REQUEST, async {
                    self.inner
                        .request(FindCalendarHomeSet::new(principal.path()))
                        .await
                        .map_err(|e| DomainError::permanent(format!("FindCalendarHomeSet: {e}")))
                })
                .await?;
                let first = resp
                    .home_sets
                    .into_iter()
                    .next()
                    .ok_or_else(|| DomainError::permanent("no calendar-home-set returned"))?;
                Ok::<_, DomainError>(first.path().to_string())
            })
            .await
            .cloned()
    }

    pub async fn list_calendars(&self) -> Result<Vec<CalendarInfo>, DomainError> {
        let home = self.calendar_home().await?;
        let resp = with_timeout("FindCalendars", CALDAV_REQUEST, async {
            self.inner
                .request(FindCalendars::new(&home))
                .await
                .map_err(|e| DomainError::permanent(format!("FindCalendars: {e}")))
        })
        .await?;

        let props: [&libdav::PropertyName<'_, '_>; 2] =
            [&names::DISPLAY_NAME, &names::CALENDAR_COLOUR];

        let mut out = Vec::with_capacity(resp.calendars.len());
        for cal in resp.calendars {
            let combined = with_timeout("GetProperties", CALDAV_REQUEST, async {
                self.inner
                    .request(GetProperties::new(&cal.href, &props))
                    .await
                    .map_err(|e| DomainError::permanent(format!("GetProperties: {e}")))
            })
            .await;

            let (name, color) = match combined {
                Ok(r) => {
                    // r.values keeps request order: [DISPLAY_NAME, CALENDAR_COLOUR].
                    let mut iter = r.values.into_iter();
                    let name = iter.next().and_then(|(_, v)| v);
                    let color = iter.next().and_then(|(_, v)| v);
                    (name, color)
                }
                Err(e) => {
                    tracing::warn!(calendar = %cal.href, error = %e, "PROPFIND failed");
                    (None, None)
                }
            };
            out.push(CalendarInfo {
                id: cal.href,
                display_name: name.unwrap_or_else(|| "(unnamed)".to_string()),
                color,
            });
        }
        Ok(out)
    }

    pub async fn list_events(
        &self,
        calendar_href: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> Result<Vec<EventSummary>, DomainError> {
        let start_s = fmt_caldav_dt(start);
        let end_s = fmt_caldav_dt(end);
        let body = build_calendar_query_xml(&start_s, &end_s);

        let url = build_calendar_url(&self.base_url, calendar_href)?;
        let req = Request::builder()
            .method("REPORT")
            .uri(url)
            .header("Content-Type", "application/xml; charset=utf-8")
            .header("Depth", "1")
            .body(Full::new(Bytes::from(body)))
            .map_err(|e| DomainError::permanent(format!("build REPORT: {e}")))?;

        let resp = with_timeout("calendar-query expand REPORT", CALDAV_REQUEST, async {
            self.raw
                .clone()
                .oneshot(req)
                .await
                .map_err(|e| DomainError::transient(format!("REPORT: {e}")))
        })
        .await?;

        let status = resp.status();
        if !status.is_success() && status.as_u16() != 207 {
            return Err(DomainError::permanent(format!(
                "calendar-query REPORT: status {status}"
            )));
        }

        let body_bytes = resp
            .into_body()
            .collect()
            .await
            .map_err(|e| DomainError::transient(format!("read REPORT body: {e}")))?
            .to_bytes();
        let body_str = std::str::from_utf8(&body_bytes)
            .map_err(|e| DomainError::permanent(format!("non-utf8 REPORT body: {e}")))?;

        parse_multistatus_calendar_data(body_str)
    }

    pub async fn get_event(
        &self,
        calendar_href: &str,
        uid_or_href: &str,
    ) -> Result<EventDetail, DomainError> {
        let href = href_for(calendar_href, uid_or_href);
        let resp = with_timeout("GetCalendarResources", CALDAV_REQUEST, async {
            self.inner
                .request(GetCalendarResources::new(calendar_href).with_hrefs([href.clone()]))
                .await
                .map_err(|e| DomainError::permanent(format!("GetCalendarResources: {e}")))
        })
        .await?;
        let resource = resp
            .resources
            .into_iter()
            .next()
            .ok_or_else(|| DomainError::not_found(format!("event not found: {href}")))?;
        let content = resource.content.map_err(|status| {
            if status.as_u16() == 404 {
                DomainError::not_found(format!("event {href}"))
            } else {
                DomainError::permanent(format!("event fetch failed: status {status}"))
            }
        })?;
        parse_event_detail(&content.data, &resource.href, Some(content.etag))
    }

    pub async fn search_events(
        &self,
        query: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        calendar_href: Option<&str>,
    ) -> Result<Vec<EventSummary>, DomainError> {
        let calendars: Vec<String> = match calendar_href {
            Some(c) => vec![c.to_string()],
            None => self
                .list_calendars()
                .await?
                .into_iter()
                .map(|c| c.id)
                .collect(),
        };

        let q = query.to_lowercase();
        let results = join_all(
            calendars
                .into_iter()
                .map(|cal| async move { (cal.clone(), self.list_events(&cal, start, end).await) }),
        )
        .await;

        let mut out = Vec::new();
        for (cal, res) in results {
            match res {
                Ok(events) => {
                    for e in events {
                        if e.summary.to_lowercase().contains(&q)
                            || e.location
                                .as_ref()
                                .is_some_and(|s| s.to_lowercase().contains(&q))
                        {
                            out.push(e);
                        }
                    }
                }
                Err(e) => tracing::warn!(calendar = %cal, error = %e, "search: skipping calendar"),
            }
        }
        Ok(out)
    }

    pub async fn create_event(
        &self,
        calendar_href: &str,
        p: CreateEventParams,
    ) -> Result<EventSummary, DomainError> {
        let uid = Uuid::new_v4().to_string();
        let ical_text = build_vevent(&uid, &p);

        let href = format!(
            "{}{}.ics",
            calendar_href.trim_end_matches('/').to_string() + "/",
            uid
        );
        let resp = with_timeout("PutResource", CALDAV_REQUEST, async {
            self.inner
                .request(
                    PutResource::new(&href)
                        .create(ical_text.clone(), "text/calendar; charset=utf-8"),
                )
                .await
                .map_err(|e| DomainError::permanent(format!("PutResource: {e}")))
        })
        .await?;

        Ok(EventSummary {
            uid,
            href,
            summary: p.title,
            start: p.start.to_rfc3339(),
            end: p.end.to_rfc3339(),
            location: p.location,
            all_day: false,
            etag: resp.etag,
            instance_id: None,
        })
    }
}

// ---- helpers ----

fn fmt_caldav_dt(dt: DateTime<Utc>) -> String {
    dt.format("%Y%m%dT%H%M%SZ").to_string()
}

fn href_for(calendar_href: &str, uid_or_href: &str) -> String {
    if uid_or_href.starts_with('/')
        || uid_or_href.starts_with("http://")
        || uid_or_href.starts_with("https://")
    {
        uid_or_href.to_string()
    } else {
        let stem = uid_or_href.trim_end_matches(".ics");
        format!("{}/{stem}.ics", calendar_href.trim_end_matches('/'))
    }
}

/// Build the `<C:calendar-query>` REPORT body that asks iCloud to expand
/// recurring events between [start, end]. The server returns one VEVENT per
/// occurrence (with RECURRENCE-ID set, RRULE stripped); EXDATE and
/// overridden instances are applied for us.
fn build_calendar_query_xml(start: &str, end: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data>
      <C:expand start="{start}" end="{end}"/>
    </C:calendar-data>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start}" end="{end}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"#
    )
}

/// Compose the absolute URL for a CalDAV REPORT against `calendar_href`.
/// libdav returns calendar hrefs as path-only strings; iCloud's regional
/// CalDAV routing accepts requests against the base host.
fn build_calendar_url(base: &Uri, calendar_href: &str) -> Result<Uri, DomainError> {
    if calendar_href.starts_with("http://") || calendar_href.starts_with("https://") {
        return calendar_href.parse().map_err(|e: http::uri::InvalidUri| {
            DomainError::permanent(format!("invalid url: {e}"))
        });
    }
    let scheme = base.scheme_str().unwrap_or("https");
    let authority = base
        .authority()
        .ok_or_else(|| DomainError::permanent("CalDAV base URL missing authority"))?
        .as_str();
    let path = if calendar_href.starts_with('/') {
        calendar_href.to_string()
    } else {
        format!("/{calendar_href}")
    };
    format!("{scheme}://{authority}{path}")
        .parse()
        .map_err(|e: http::uri::InvalidUri| {
            DomainError::permanent(format!("invalid calendar URL: {e}"))
        })
}

/// Parse a CalDAV `<D:multistatus>` body produced by a `calendar-query`
/// REPORT with `<C:expand>`. Each `<D:response>` carries one `<C:calendar-data>`
/// chunk that may itself contain several VEVENT components (one per expanded
/// occurrence). Emits one `EventSummary` per VEVENT, preserving RECURRENCE-ID
/// in `instance_id` so callers can disambiguate occurrences of the same UID.
fn parse_multistatus_calendar_data(xml: &str) -> Result<Vec<EventSummary>, DomainError> {
    use quick_xml::events::Event;
    use quick_xml::Reader;

    // Do NOT enable trim_text globally: it strips the trailing `\n` from the
    // final `END:VCALENDAR\r\n` inside `<C:calendar-data>`, which the
    // icalendar parser then rejects. We trim href/getetag values manually.
    let mut reader = Reader::from_str(xml);

    let mut summaries = Vec::new();
    let mut current_href: Option<String> = None;
    let mut current_etag: Option<String> = None;
    let mut current_data: Option<String> = None;
    let mut text_buf: Option<String> = None;
    let mut in_response = false;
    let mut capture: Capture = Capture::None;

    loop {
        match reader.read_event() {
            Ok(Event::Start(ref e)) => {
                let name = local_name(e.name().as_ref());
                match name.as_str() {
                    "response" => {
                        in_response = true;
                        current_href = None;
                        current_etag = None;
                        current_data = None;
                    }
                    "href" if in_response && capture == Capture::None => {
                        capture = Capture::Href;
                        text_buf = Some(String::new());
                    }
                    "getetag" if in_response => {
                        capture = Capture::Etag;
                        text_buf = Some(String::new());
                    }
                    "calendar-data" if in_response => {
                        capture = Capture::Data;
                        text_buf = Some(String::new());
                    }
                    _ => {}
                }
            }
            Ok(Event::Text(t)) => {
                if let Some(buf) = &mut text_buf {
                    buf.push_str(
                        &t.unescape()
                            .map_err(|e| DomainError::permanent(format!("xml unescape: {e}")))?,
                    );
                }
            }
            Ok(Event::CData(t)) => {
                if let Some(buf) = &mut text_buf {
                    buf.push_str(&String::from_utf8_lossy(t.as_ref()));
                }
            }
            Ok(Event::End(ref e)) => {
                let name = local_name(e.name().as_ref());
                match name.as_str() {
                    "href" if capture == Capture::Href => {
                        current_href = text_buf.take();
                        capture = Capture::None;
                    }
                    "getetag" if capture == Capture::Etag => {
                        current_etag = text_buf.take();
                        capture = Capture::None;
                    }
                    "calendar-data" if capture == Capture::Data => {
                        current_data = text_buf.take();
                        capture = Capture::None;
                    }
                    "response" if in_response => {
                        in_response = false;
                        if let (Some(href), Some(data)) = (current_href.take(), current_data.take())
                        {
                            let etag = current_etag.take();
                            for s in parse_expanded_vcalendar(&data, &href, etag.as_deref()) {
                                summaries.push(s);
                            }
                        }
                    }
                    _ => {}
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(DomainError::permanent(format!("xml parse: {e}"))),
            _ => {}
        }
    }

    Ok(summaries)
}

#[derive(Debug, PartialEq, Eq)]
enum Capture {
    None,
    Href,
    Etag,
    Data,
}

fn local_name(qname: &[u8]) -> String {
    let s = std::str::from_utf8(qname).unwrap_or("");
    match s.rfind(':') {
        Some(idx) => s[idx + 1..].to_string(),
        None => s.to_string(),
    }
}

/// Walk every VEVENT in a (possibly multi-component) VCALENDAR and emit one
/// `EventSummary` per event. Used after server-side `<C:expand>` where iCloud
/// returns one VEVENT per occurrence.
fn parse_expanded_vcalendar(data: &str, href: &str, etag: Option<&str>) -> Vec<EventSummary> {
    let Ok(cal) = data.parse::<ICalendar>() else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for component in &cal.components {
        if let CalendarComponent::Event(event) = component {
            let (start, all_day) = dpt_to_string(event.get_start());
            let (end, _) = dpt_to_string(event.get_end());
            let instance_id = event.property_value("RECURRENCE-ID").map(String::from);
            out.push(EventSummary {
                uid: event.get_uid().unwrap_or("").to_string(),
                href: href.to_string(),
                summary: event.get_summary().unwrap_or("").to_string(),
                start,
                end,
                location: event.get_location().map(String::from),
                all_day,
                etag: etag.map(String::from),
                instance_id,
            });
        }
    }
    out
}

fn parse_event_detail(
    data: &str,
    href: &str,
    etag: Option<String>,
) -> Result<EventDetail, DomainError> {
    let cal: ICalendar = data
        .parse()
        .map_err(|e: String| DomainError::permanent(format!("ical parse: {e}")))?;
    let event = cal
        .components
        .iter()
        .find_map(|c| match c {
            CalendarComponent::Event(e) => Some(e),
            _ => None,
        })
        .ok_or_else(|| DomainError::permanent("no VEVENT in calendar-data"))?;

    let (start, all_day) = dpt_to_string(event.get_start());
    let (end, _) = dpt_to_string(event.get_end());

    let organizer = event
        .property_value("ORGANIZER")
        .map(|s| s.trim_start_matches("mailto:").to_string());

    let attendees: Vec<String> = event
        .multi_properties()
        .get("ATTENDEE")
        .map(|props| {
            props
                .iter()
                .map(|p| p.value().trim_start_matches("mailto:").to_string())
                .collect()
        })
        .unwrap_or_default();

    let status = event.property_value("STATUS").map(String::from);

    Ok(EventDetail {
        uid: event.get_uid().unwrap_or("").to_string(),
        href: href.to_string(),
        summary: event.get_summary().unwrap_or("").to_string(),
        description: event.get_description().map(String::from),
        location: event.get_location().map(String::from),
        start,
        end,
        all_day,
        status,
        organizer,
        attendees,
        etag,
        ical: data.to_string(),
    })
}

fn dpt_to_string(dpt: Option<icalendar::DatePerhapsTime>) -> (String, bool) {
    use icalendar::{CalendarDateTime, DatePerhapsTime};
    match dpt {
        Some(DatePerhapsTime::DateTime(CalendarDateTime::Utc(dt))) => (dt.to_rfc3339(), false),
        Some(DatePerhapsTime::DateTime(CalendarDateTime::Floating(ndt))) => {
            (ndt.format("%Y-%m-%dT%H:%M:%S").to_string(), false)
        }
        Some(DatePerhapsTime::DateTime(CalendarDateTime::WithTimezone { date_time, tzid })) => (
            format!("{}[{}]", date_time.format("%Y-%m-%dT%H:%M:%S"), tzid),
            false,
        ),
        Some(DatePerhapsTime::Date(d)) => (d.format("%Y-%m-%d").to_string(), true),
        None => (String::new(), false),
    }
}

/// Build a full VCALENDAR/VEVENT block for `create_event`.
///
/// Adds DTSTAMP (required by RFC 5545), CALSCALE:GREGORIAN, and METHOD:REQUEST
/// when attendees are present (so iCloud actually mails invitations). Attendee
/// lines include `RSVP=TRUE;PARTSTAT=NEEDS-ACTION;ROLE=REQ-PARTICIPANT`.
fn build_vevent(uid: &str, p: &CreateEventParams) -> String {
    let mut ev = ICalEvent::new();
    ev.uid(uid).summary(&p.title).starts(p.start).ends(p.end);
    ev.add_property("DTSTAMP", fmt_caldav_dt(Utc::now()));
    if let Some(d) = &p.description {
        ev.description(d);
    }
    if let Some(l) = &p.location {
        ev.location(l);
    }
    for a in &p.attendees {
        // Build ATTENDEE with structured parameters via icalendar's Property API
        // so that semicolons separating params survive serialization (raw
        // values would have `;` escaped as `\;`, breaking parameter parsing).
        let mut prop = Property::new("ATTENDEE", format!("mailto:{a}"));
        prop.append_parameter(("RSVP", "TRUE"));
        prop.append_parameter(("PARTSTAT", "NEEDS-ACTION"));
        prop.append_parameter(("ROLE", "REQ-PARTICIPANT"));
        ev.append_multi_property(prop);
    }
    ev.append_property(Property::new(
        "ORGANIZER",
        format!("mailto:{}", p.organizer),
    ));
    let event = ev.done();

    let mut cal = ICalendar::new();
    cal.push(event);
    // VERSION/PRODID/CALSCALE are emitted by `icalendar` itself - do not
    // re-append, or the output will have duplicate top-level properties.
    let method = if p.attendees.is_empty() {
        "PUBLISH"
    } else {
        "REQUEST"
    };
    cal.append_property(("METHOD", method));
    cal.to_string()
}

/// Strip RFC 5545 line folds (`\r\n ` or `\n ` continuations). Used in tests
/// to assert against the logical content rather than the wire format.
#[cfg(test)]
fn unfold_ical(s: &str) -> String {
    s.replace("\r\n ", "").replace("\n ", "")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn caldav_dt_format() {
        let dt = Utc.with_ymd_and_hms(2026, 5, 14, 9, 30, 0).unwrap();
        assert_eq!(fmt_caldav_dt(dt), "20260514T093000Z");
    }

    #[test]
    fn href_for_bare_uid_appends_ics() {
        assert_eq!(
            href_for("/123/calendars/abc/", "evt1"),
            "/123/calendars/abc/evt1.ics"
        );
    }

    #[test]
    fn href_for_strips_trailing_slash_and_ics_suffix() {
        assert_eq!(
            href_for("/123/calendars/abc", "evt1.ics"),
            "/123/calendars/abc/evt1.ics"
        );
    }

    #[test]
    fn href_for_passes_through_absolute_path() {
        assert_eq!(
            href_for("/123/calendars/abc/", "/123/calendars/abc/evt1.ics"),
            "/123/calendars/abc/evt1.ics"
        );
    }

    #[test]
    fn href_for_passes_through_full_url() {
        let full = "https://p01-caldav.icloud.com/123/calendars/abc/evt1.ics";
        assert_eq!(href_for("/123/calendars/abc/", full), full);
    }

    #[test]
    fn href_for_does_not_match_httpx_prefix() {
        // "httpx" is a UID, not a URL - must be treated as a bare UID and
        // get `.ics` appended.
        assert_eq!(href_for("/cal/", "httpx-event-1"), "/cal/httpx-event-1.ics");
    }

    #[test]
    fn dpt_string_utc_datetime() {
        use icalendar::{CalendarDateTime, DatePerhapsTime};
        let dt = Utc.with_ymd_and_hms(2026, 5, 14, 9, 30, 0).unwrap();
        let (s, all_day) =
            dpt_to_string(Some(DatePerhapsTime::DateTime(CalendarDateTime::Utc(dt))));
        assert!(s.starts_with("2026-05-14T09:30:00"));
        assert!(!all_day);
    }

    #[test]
    fn dpt_string_date_only_is_all_day() {
        use icalendar::DatePerhapsTime;
        let d = chrono::NaiveDate::from_ymd_opt(2026, 5, 14).unwrap();
        let (s, all_day) = dpt_to_string(Some(DatePerhapsTime::Date(d)));
        assert_eq!(s, "2026-05-14");
        assert!(all_day);
    }

    #[test]
    fn dpt_string_none() {
        let (s, all_day) = dpt_to_string(None);
        assert!(s.is_empty());
        assert!(!all_day);
    }

    const SAMPLE_VEVENT: &str = "\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//test//EN\r
BEGIN:VEVENT\r
UID:abc-123\r
DTSTAMP:20260514T090000Z\r
DTSTART:20260514T090000Z\r
DTEND:20260514T100000Z\r
SUMMARY:Team sync\r
LOCATION:Room 1\r
DESCRIPTION:weekly\r
ORGANIZER:mailto:me@example.com\r
ATTENDEE:mailto:a@example.com\r
ATTENDEE:mailto:b@example.com\r
STATUS:CONFIRMED\r
END:VEVENT\r
END:VCALENDAR\r
";

    #[test]
    fn parse_summary_extracts_basic_fields() {
        let v = parse_expanded_vcalendar(SAMPLE_VEVENT, "/cal/abc-123.ics", Some("etag1"));
        assert_eq!(v.len(), 1);
        let s = &v[0];
        assert_eq!(s.uid, "abc-123");
        assert_eq!(s.summary, "Team sync");
        assert_eq!(s.location.as_deref(), Some("Room 1"));
        assert_eq!(s.href, "/cal/abc-123.ics");
        assert_eq!(s.etag.as_deref(), Some("etag1"));
        assert!(!s.all_day);
        assert!(s.start.starts_with("2026-05-14T09:00:00"));
        assert!(s.end.starts_with("2026-05-14T10:00:00"));
        assert!(s.instance_id.is_none());
    }

    #[test]
    fn parse_detail_extracts_attendees_and_status() {
        let d = parse_event_detail(SAMPLE_VEVENT, "/cal/abc-123.ics", None).unwrap();
        assert_eq!(d.description.as_deref(), Some("weekly"));
        assert_eq!(d.organizer.as_deref(), Some("me@example.com"));
        assert_eq!(d.status.as_deref(), Some("CONFIRMED"));
        assert_eq!(
            d.attendees,
            vec!["a@example.com".to_string(), "b@example.com".to_string()]
        );
        assert!(d.ical.contains("UID:abc-123"));
    }

    #[test]
    fn parse_returns_empty_for_vcalendar_without_vevent() {
        let bad = "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n";
        assert!(parse_expanded_vcalendar(bad, "/x.ics", None).is_empty());
    }

    const EXPANDED_RESPONSE: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>/cal/weekly.ics</D:href>
    <D:propstat>
      <D:prop>
        <D:getetag>"e1"</D:getetag>
        <C:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:weekly-uid
DTSTAMP:20260514T080000Z
DTSTART:20260514T090000Z
DTEND:20260514T100000Z
RECURRENCE-ID:20260514T090000Z
SUMMARY:Weekly sync
END:VEVENT
BEGIN:VEVENT
UID:weekly-uid
DTSTAMP:20260514T080000Z
DTSTART:20260521T090000Z
DTEND:20260521T100000Z
RECURRENCE-ID:20260521T090000Z
SUMMARY:Weekly sync
END:VEVENT
END:VCALENDAR</C:calendar-data>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>
"#;

    const FIXTURE_FORMAT_RESPONSE: &str = r#"<?xml version="1.0" encoding="utf-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <response>
    <href>/cal/single.ics</href>
    <propstat>
      <prop>
        <getetag>"x1"</getetag>
        <C:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:single-uid
DTSTAMP:20260514T080000Z
DTSTART:20260514T090000Z
DTEND:20260514T100000Z
SUMMARY:One-off
END:VEVENT
END:VCALENDAR
</C:calendar-data>
      </prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
</multistatus>"#;

    #[test]
    fn multistatus_handles_default_namespace_without_prefix() {
        let v = parse_multistatus_calendar_data(FIXTURE_FORMAT_RESPONSE).unwrap();
        assert_eq!(
            v.len(),
            1,
            "fixture-shaped multistatus should yield 1 event"
        );
        assert_eq!(v[0].uid, "single-uid");
        assert_eq!(v[0].summary, "One-off");
    }

    /// Mirrors `tests/fixtures/multiget_events.xml`: default DAV: namespace
    /// (no `D:` prefix), `&#13;` carriage-return entities inside calendar-data.
    /// Production iCloud responses use the same shape.
    const FIXTURE_WITH_CR_ENTITIES: &str = r#"<?xml version="1.0" encoding="utf-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <response>
    <href>/1234/calendars/work/event-1.ics</href>
    <propstat>
      <prop>
        <getetag>"e-1"</getetag>
        <C:calendar-data>BEGIN:VCALENDAR&#13;
VERSION:2.0&#13;
PRODID:-//test//EN&#13;
BEGIN:VEVENT&#13;
UID:event-1&#13;
DTSTAMP:20260514T080000Z&#13;
DTSTART:20260514T090000Z&#13;
DTEND:20260514T100000Z&#13;
SUMMARY:Standup&#13;
LOCATION:Zoom&#13;
END:VEVENT&#13;
END:VCALENDAR&#13;
</C:calendar-data>
      </prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
</multistatus>"#;

    #[test]
    fn multistatus_handles_cr_entities_in_calendar_data() {
        let v = parse_multistatus_calendar_data(FIXTURE_WITH_CR_ENTITIES).unwrap();
        assert_eq!(
            v.len(),
            1,
            "&#13; entities inside calendar-data must round-trip into a parseable VCALENDAR"
        );
        assert_eq!(v[0].uid, "event-1");
        assert_eq!(v[0].summary, "Standup");
    }

    #[test]
    fn multistatus_emits_one_summary_per_expanded_instance() {
        let v = parse_multistatus_calendar_data(EXPANDED_RESPONSE).unwrap();
        assert_eq!(v.len(), 2, "two expanded occurrences expected");
        assert_eq!(v[0].uid, "weekly-uid");
        assert_eq!(v[1].uid, "weekly-uid");
        assert_eq!(v[0].href, "/cal/weekly.ics");
        assert_eq!(v[1].href, "/cal/weekly.ics");
        assert_eq!(v[0].etag.as_deref(), Some("\"e1\""));
        assert!(v[0].start.starts_with("2026-05-14T09:00:00"));
        assert!(v[1].start.starts_with("2026-05-21T09:00:00"));
        assert!(v[0].instance_id.as_deref().is_some());
        assert!(v[1].instance_id.as_deref().is_some());
    }

    #[test]
    fn build_calendar_url_appends_path_to_base() {
        let base: Uri = "https://caldav.icloud.com".parse().unwrap();
        let u = build_calendar_url(&base, "/123/calendars/abc/").unwrap();
        assert_eq!(
            u.to_string(),
            "https://caldav.icloud.com/123/calendars/abc/"
        );
    }

    #[test]
    fn build_calendar_url_passes_absolute_through() {
        let base: Uri = "https://caldav.icloud.com".parse().unwrap();
        let abs = "https://p01-caldav.icloud.com/123/calendars/abc/";
        let u = build_calendar_url(&base, abs).unwrap();
        assert_eq!(u.to_string(), abs);
    }

    #[test]
    fn build_calendar_query_xml_includes_expand_and_time_range() {
        let xml = build_calendar_query_xml("20260514T000000Z", "20260615T000000Z");
        assert!(xml.contains("<C:expand start=\"20260514T000000Z\" end=\"20260615T000000Z\"/>"));
        assert!(xml.contains("<C:time-range start=\"20260514T000000Z\" end=\"20260615T000000Z\"/>"));
        assert!(xml.contains("<C:comp-filter name=\"VEVENT\">"));
    }

    fn sample_create_params(attendees: Vec<&str>) -> CreateEventParams {
        CreateEventParams {
            title: "Standup".into(),
            start: Utc.with_ymd_and_hms(2026, 5, 14, 9, 0, 0).unwrap(),
            end: Utc.with_ymd_and_hms(2026, 5, 14, 9, 30, 0).unwrap(),
            description: Some("daily".into()),
            location: Some("Zoom".into()),
            attendees: attendees.into_iter().map(String::from).collect(),
            organizer: "me@example.com".into(),
        }
    }

    #[test]
    fn build_vevent_includes_dtstamp_and_method_request() {
        let p = sample_create_params(vec!["alice@example.com"]);
        let s = unfold_ical(&build_vevent("uid-1", &p));
        assert!(s.contains("BEGIN:VEVENT"));
        assert!(s.contains("UID:uid-1"));
        assert!(s.contains("DTSTAMP:"));
        assert!(s.contains("CALSCALE:GREGORIAN"));
        assert!(s.contains("METHOD:REQUEST"));
        assert!(s.contains("RSVP=TRUE"));
        assert!(s.contains("PARTSTAT=NEEDS-ACTION"));
        assert!(s.contains("ROLE=REQ-PARTICIPANT"));
        assert!(s.contains("mailto:alice@example.com"));
        assert!(s.contains("ORGANIZER:mailto:me@example.com"));
        // VCALENDAR-level properties are emitted exactly once.
        assert_eq!(s.matches("VERSION:2.0").count(), 1);
        assert_eq!(s.matches("CALSCALE:GREGORIAN").count(), 1);
        assert_eq!(s.matches("METHOD:REQUEST").count(), 1);
    }

    #[test]
    fn build_vevent_without_attendees_uses_method_publish() {
        let p = sample_create_params(vec![]);
        let s = build_vevent("uid-2", &p);
        assert!(s.contains("METHOD:PUBLISH"));
        assert!(!s.contains("ATTENDEE"));
    }
}
