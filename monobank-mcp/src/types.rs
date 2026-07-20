//! Data types shared between the API client, the store, and the sync engines.
//!
//! Mirrors the Monobank Personal API shape closely (see
//! https://api.monobank.ua/docs/) but converts amounts to signed minor units
//! and timestamps to unix seconds for storage.

use serde::{Deserialize, Serialize};

/// Single account from /personal/client-info.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MonoAccount {
    pub id: String,
    #[serde(default)]
    pub iban: Option<String>,
    /// Monobank type: 'card' | 'fop' | 'jar' | 'deposit' | 'eAid'.
    #[serde(default, rename = "type")]
    pub r#type: Option<String>,
    /// ISO 4217 numeric code.
    #[serde(rename = "currencyCode")]
    pub currency_code: i64,
    #[serde(default, rename = "maskedPan")]
    pub masked_pan: Option<Vec<String>>,
    /// Current balance in minor units. INCLUDES the credit line (see
    /// `credit_limit`). Present on card/fop accounts.
    #[serde(default)]
    pub balance: Option<i64>,
    /// Credit line in minor units, baked into `balance`. Real own funds =
    /// `balance - credit_limit`. Absent/zero for accounts with no overdraft.
    #[serde(default, rename = "creditLimit")]
    pub credit_limit: Option<i64>,
    /// Optional human label - not in the API; we keep it for the local row.
    #[serde(default)]
    pub label: Option<String>,
}

/// /personal/client-info payload.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientInfo {
    #[serde(rename = "clientId")]
    pub client_id: String,
    pub name: String,
    pub accounts: Vec<MonoAccount>,
    /// Permissions string; not used by us beyond auditing.
    #[serde(default)]
    pub permissions: Option<String>,
}

/// One statement row from /personal/statement/{account}/{from}/{to}.
/// Amounts are signed integer minor units. Outflow is negative.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MonoStatement {
    pub id: String,
    pub time: i64,
    pub description: String,
    #[serde(default)]
    pub mcc: Option<i64>,
    #[serde(default, rename = "originalMcc")]
    pub original_mcc: Option<i64>,
    pub amount: i64,
    #[serde(rename = "operationAmount")]
    pub operation_amount: i64,
    #[serde(rename = "currencyCode")]
    pub currency_code: i64,
    #[serde(default, rename = "commissionRate")]
    pub commission_rate: Option<i64>,
    #[serde(default, rename = "cashbackAmount")]
    pub cashback_amount: Option<i64>,
    #[serde(default)]
    pub balance: Option<i64>,
    #[serde(default)]
    pub hold: Option<bool>,
    #[serde(default)]
    pub counter_name: Option<String>,
    #[serde(default, rename = "counterEdrpou")]
    pub counter_edrpou: Option<String>,
    #[serde(default, rename = "counterIban")]
    pub counter_iban: Option<String>,
}

/// `source` value stored in `mono_import_runs.source`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunSource {
    Backfill,
    Sync,
}

impl RunSource {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Backfill => "backfill",
            Self::Sync => "sync",
        }
    }
}
