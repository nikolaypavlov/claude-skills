//! Shared test helpers: synthetic Monobank API payloads + httpmock setup.
//!
//! Fixtures are GENERATED, not real data. The seeded approach keeps tests
//! deterministic while avoiding any chance of personal info landing in the
//! repo.

// Each integration test file declares `mod common;` but uses a different
// subset of the helpers, so dead_code warnings here are expected.
#![allow(dead_code)]

use httpmock::Method::GET;
use httpmock::MockServer;
use serde_json::{json, Value};

pub const FIXTURE_ACCOUNT_ID: &str = "acc_abcd_1234";
pub const FIXTURE_CCY_UAH: i64 = 980;

/// Build a synthetic /personal/client-info response.
pub fn client_info_fixture() -> Value {
    json!({
        "clientId": "synthetic-client-id-0001",
        "name": "Test User",
        "webHookUrl": "",
        "permissions": "psf",
        "accounts": [
            {
                "id": FIXTURE_ACCOUNT_ID,
                "sendId": "x" ,
                "balance": 1_234_567,
                "creditLimit": 0,
                "type": "black",
                "currencyCode": FIXTURE_CCY_UAH,
                "cashbackType": "Miles",
                "maskedPan": ["537541******1234"],
                "iban": "UA000000000000000000000000001"
            }
        ],
        "jars": []
    })
}

/// Build a synthetic /personal/statement response of N rows. `start_ts` is
/// the earliest item; each subsequent item is +600s and -25000 minor units.
pub fn statement_fixture(start_ts: i64, n: usize) -> Value {
    let mut items = Vec::with_capacity(n);
    for i in 0..n {
        items.push(json!({
            "id": format!("stmt_{:08}_{}", start_ts, i),
            "time": start_ts + (i as i64) * 600,
            "description": format!("Synthetic merchant #{}", i),
            "mcc": 5411,
            "originalMcc": 5411,
            "hold": false,
            "amount": -25_000_i64 - (i as i64) * 100,
            "operationAmount": -25_000_i64 - (i as i64) * 100,
            "currencyCode": FIXTURE_CCY_UAH,
            "commissionRate": 0,
            "cashbackAmount": 0,
            "balance": 1_234_567_i64 - (i as i64) * 25_000,
        }));
    }
    Value::Array(items)
}

/// Mount /personal/client-info on a mock server.
pub fn mount_client_info(server: &MockServer, body: &Value) {
    let body = body.clone();
    server.mock(|when, then| {
        when.method(GET).path("/personal/client-info");
        then.status(200)
            .header("content-type", "application/json")
            .body(body.to_string());
    });
}

/// Mount /personal/statement/{account}/{from}/{to} on a mock server.
pub fn mount_statement_range(
    server: &MockServer,
    account: &str,
    from_ts: i64,
    to_ts: i64,
    body: &Value,
) {
    let body = body.clone();
    let path = format!("/personal/statement/{account}/{from_ts}/{to_ts}");
    server.mock(|when, then| {
        when.method(GET).path(path);
        then.status(200)
            .header("content-type", "application/json")
            .body(body.to_string());
    });
}

/// Mount a catch-all empty-statement response on /personal/statement/{account}/...
/// using a path-prefix match. Used by tests that exercise many chunks without
/// caring about their exact bounds.
pub fn mount_statement_prefix_empty(server: &MockServer, account: &str) {
    let prefix = format!("/personal/statement/{account}/");
    server.mock(|when, then| {
        when.method(GET).path_prefix(prefix);
        then.status(200)
            .header("content-type", "application/json")
            .body("[]");
    });
}
