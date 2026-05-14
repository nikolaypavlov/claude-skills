//! CalDAV client wrapper around [`libdav`].
//!
//! Flow:
//!     1. `Client::new` builds a hyper-rustls https client, wraps it with Basic auth
//!        (tower_http), then bootstraps a [`CalDavClient`] via DNS service discovery.
//!     2. `list_calendars` finds the principal -> calendar-home-set -> collections,
//!        then queries displayname + colour for each.
//!     3. `list_events` does ListCalendarResources(time-range) then GetCalendarResources
//!        (multiget) for the iCalendar data.
//!     4. `create_event` builds a VEVENT with `icalendar` and PUTs it with If-None-Match.

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use http::Uri;
use hyper_rustls::HttpsConnectorBuilder;
use hyper_util::client::legacy::{connect::HttpConnector, Client as HyperClient};
use hyper_util::rt::TokioExecutor;
use icalendar::{
    Calendar as ICalendar, CalendarComponent, Component, Event as ICalEvent, EventLike,
};
use libdav::caldav::{
    FindCalendarHomeSet, FindCalendars, GetCalendarResources, ListCalendarResources,
};
use libdav::dav::{GetProperty, PutResource, WebDavClient};
use libdav::{names, CalDavClient, FetchedResource};
use tokio::sync::OnceCell;
use tower_http::auth::AddAuthorization;
use uuid::Uuid;

use crate::config::{Config, CALDAV_BASE};

type AuthClient =
    AddAuthorization<HyperClient<hyper_rustls::HttpsConnector<HttpConnector>, String>>;

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
    home: OnceCell<String>,
}

impl Client {
    pub async fn new(config: &Config) -> Result<Self> {
        let base_url: Uri = CALDAV_BASE.parse().context("invalid CALDAV_BASE")?;

        let connector = HttpsConnectorBuilder::new()
            .with_native_roots()
            .context("loading native TLS roots")?
            .https_only()
            .enable_http1()
            .build();
        let hyper_client = HyperClient::builder(TokioExecutor::new()).build(connector);
        let auth_client =
            AddAuthorization::basic(hyper_client, &config.apple_id, &config.app_password);

        let webdav = WebDavClient::new(base_url, auth_client);
        let caldav = CalDavClient::bootstrap_via_service_discovery(webdav)
            .await
            .context("CalDAV service discovery (caldav.icloud.com)")?;

        Ok(Self {
            inner: caldav,
            home: OnceCell::new(),
        })
    }

    async fn calendar_home(&self) -> Result<String> {
        self.home
            .get_or_try_init(|| async {
                let principal = self
                    .inner
                    .find_current_user_principal()
                    .await
                    .context("find_current_user_principal")?
                    .ok_or_else(|| anyhow!("server did not return a current-user-principal"))?;
                let resp = self
                    .inner
                    .request(FindCalendarHomeSet::new(principal.path()))
                    .await
                    .map_err(|e| anyhow!("FindCalendarHomeSet: {e}"))?;
                let first = resp
                    .home_sets
                    .into_iter()
                    .next()
                    .ok_or_else(|| anyhow!("no calendar-home-set returned"))?;
                Ok::<_, anyhow::Error>(first.path().to_string())
            })
            .await
            .cloned()
    }

    pub async fn list_calendars(&self) -> Result<Vec<CalendarInfo>> {
        let home = self.calendar_home().await?;
        let resp = self
            .inner
            .request(FindCalendars::new(&home))
            .await
            .map_err(|e| anyhow!("FindCalendars: {e}"))?;

        let mut out = Vec::with_capacity(resp.calendars.len());
        for cal in resp.calendars {
            let name = self
                .inner
                .request(GetProperty::new(&cal.href, &names::DISPLAY_NAME))
                .await
                .ok()
                .and_then(|r| r.value);
            let color = self
                .inner
                .request(GetProperty::new(&cal.href, &names::CALENDAR_COLOUR))
                .await
                .ok()
                .and_then(|r| r.value);
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
    ) -> Result<Vec<EventSummary>> {
        let start_s = fmt_caldav_dt(start);
        let end_s = fmt_caldav_dt(end);

        let listing = self
            .inner
            .request(
                ListCalendarResources::new(calendar_href)
                    .with_component_and_time_range("VEVENT", Some(&start_s), Some(&end_s))
                    .map_err(|e| anyhow!("invalid time-range: {e}"))?,
            )
            .await
            .map_err(|e| anyhow!("ListCalendarResources: {e}"))?;

        let hrefs: Vec<String> = listing
            .resources
            .into_iter()
            .filter(|r| !r.resource_type.is_collection)
            .map(|r| r.href)
            .collect();
        if hrefs.is_empty() {
            return Ok(Vec::new());
        }

        let fetched = self
            .inner
            .request(GetCalendarResources::new(calendar_href).with_hrefs(&hrefs))
            .await
            .map_err(|e| anyhow!("GetCalendarResources: {e}"))?;

        let mut out = Vec::with_capacity(fetched.resources.len());
        for r in fetched.resources {
            if let Some(s) = into_summary(&r) {
                out.push(s);
            }
        }
        Ok(out)
    }

    pub async fn get_event(&self, calendar_href: &str, uid_or_href: &str) -> Result<EventDetail> {
        let href = href_for(calendar_href, uid_or_href);
        let resp = self
            .inner
            .request(GetCalendarResources::new(calendar_href).with_hrefs([href.clone()]))
            .await
            .map_err(|e| anyhow!("GetCalendarResources: {e}"))?;
        let resource = resp
            .resources
            .into_iter()
            .next()
            .ok_or_else(|| anyhow!("event not found: {href}"))?;
        let content = resource
            .content
            .map_err(|status| anyhow!("event fetch failed with status {status}"))?;
        parse_event_detail(&content.data, &resource.href, Some(content.etag))
    }

    pub async fn search_events(
        &self,
        query: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        calendar_href: Option<&str>,
    ) -> Result<Vec<EventSummary>> {
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
        let mut out = Vec::new();
        for cal in calendars {
            match self.list_events(&cal, start, end).await {
                Ok(events) => {
                    for e in events {
                        if e.summary.to_lowercase().contains(&q)
                            || e.location
                                .as_ref()
                                .map(|s| s.to_lowercase().contains(&q))
                                .unwrap_or(false)
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
    ) -> Result<EventSummary> {
        let uid = Uuid::new_v4().to_string();

        let mut ev = ICalEvent::new();
        ev.uid(&uid).summary(&p.title).starts(p.start).ends(p.end);
        if let Some(d) = &p.description {
            ev.description(d);
        }
        if let Some(l) = &p.location {
            ev.location(l);
        }
        for a in &p.attendees {
            ev.add_property("ATTENDEE", format!("mailto:{a}"));
        }
        ev.add_property("ORGANIZER", format!("mailto:{}", p.organizer));
        let event = ev.done();

        let mut cal = ICalendar::new();
        cal.push(event);
        cal.append_property(("PRODID", "-//icloud-mcp//EN"));
        cal.append_property(("VERSION", "2.0"));
        let ical_text = cal.to_string();

        let href = format!(
            "{}{}.ics",
            calendar_href.trim_end_matches('/').to_string() + "/",
            uid
        );
        let resp = self
            .inner
            .request(
                PutResource::new(&href).create(ical_text.clone(), "text/calendar; charset=utf-8"),
            )
            .await
            .map_err(|e| anyhow!("PutResource: {e}"))?;

        Ok(EventSummary {
            uid,
            href,
            summary: p.title,
            start: p.start.to_rfc3339(),
            end: p.end.to_rfc3339(),
            location: p.location,
            all_day: false,
            etag: resp.etag,
        })
    }
}

// ---- helpers ----

fn fmt_caldav_dt(dt: DateTime<Utc>) -> String {
    dt.format("%Y%m%dT%H%M%SZ").to_string()
}

fn href_for(calendar_href: &str, uid_or_href: &str) -> String {
    if uid_or_href.starts_with('/') || uid_or_href.starts_with("http") {
        uid_or_href.to_string()
    } else {
        let stem = uid_or_href.trim_end_matches(".ics");
        format!("{}/{stem}.ics", calendar_href.trim_end_matches('/'))
    }
}

fn into_summary(r: &FetchedResource) -> Option<EventSummary> {
    let content = r.content.as_ref().ok()?;
    parse_event_summary(&content.data, &r.href, Some(content.etag.clone())).ok()
}

fn parse_event_summary(data: &str, href: &str, etag: Option<String>) -> Result<EventSummary> {
    let cal: ICalendar = data.parse().map_err(|e| anyhow!("ical parse: {e}"))?;
    let event = cal
        .components
        .iter()
        .find_map(|c| match c {
            CalendarComponent::Event(e) => Some(e),
            _ => None,
        })
        .ok_or_else(|| anyhow!("no VEVENT in calendar-data"))?;

    let (start, all_day) = dpt_to_string(event.get_start());
    let (end, _) = dpt_to_string(event.get_end());

    Ok(EventSummary {
        uid: event.get_uid().unwrap_or("").to_string(),
        href: href.to_string(),
        summary: event.get_summary().unwrap_or("").to_string(),
        start,
        end,
        location: event.get_location().map(String::from),
        all_day,
        etag,
    })
}

fn parse_event_detail(data: &str, href: &str, etag: Option<String>) -> Result<EventDetail> {
    let cal: ICalendar = data.parse().map_err(|e| anyhow!("ical parse: {e}"))?;
    let event = cal
        .components
        .iter()
        .find_map(|c| match c {
            CalendarComponent::Event(e) => Some(e),
            _ => None,
        })
        .ok_or_else(|| anyhow!("no VEVENT in calendar-data"))?;

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
