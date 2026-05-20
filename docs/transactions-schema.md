# Transactions schema convention (cross-plugin data contract)

Цей документ - **convention, не enforced код**. Кожен ingest-плагін
(monobank-mcp, privat24-skill, майбутні bank-плагіни) добровільно
дотримується цієї форми у своїй власній `<bank>_transactions` таблиці.

personal-finance плагін **тільки читає** ці таблиці і проєктує їх у
common shape при запитах. personal-finance не оголошує і не мігрує
жодну з `<bank>_*` таблиць - вони повністю під контролем ingest-плагінів.

## 1. Per-plugin tables (required)

Кожен ingest-плагін з кодом `<bank>` володіє наступним мінімальним набором:

- `<bank>_accounts` - account metadata
- `<bank>_transactions` - transactions per shape below
- `<bank>_schema_version` - migration tracking, PK `(version)`

Опційно (рекомендовано якщо релевантно):

- `<bank>_sync_state` - per-account sync cursors (тільки якщо є API і потрібен incremental sync)
- `<bank>_import_runs` - import audit, з полями `id, source, started_at, finished_at, rows_inserted, rows_skipped, error, file_path?, file_sha256?`

## 2. Required columns у `<bank>_transactions`

| Column        | Type    | Null | Опис                                          |
|---------------|---------|------|-----------------------------------------------|
| id            | TEXT    | NO   | PK, globally unique across all bank tables    |
| account_id    | TEXT    | NO   | FK soft -> `<bank>_accounts.account_id`       |
| ts            | INTEGER | NO   | unix seconds UTC                              |
| amount_minor  | INTEGER | NO   | signed, minor units; negative = outflow       |
| currency_code | INTEGER | NO   | ISO 4217 numeric                              |
| description   | TEXT    | YES  | merchant description, may be empty            |
| raw_json      | TEXT    | NO   | full source payload, debugging                |
| imported_at   | INTEGER | NO   | unix seconds, when row was ingested           |

## 3. Optional columns (use if data source provides them)

| Column           | Type    | Опис                                      |
|------------------|---------|-------------------------------------------|
| mcc              | INTEGER | Merchant category code                    |
| counterparty     | TEXT    | Parsed counterparty name                  |
| op_amount_minor  | INTEGER | Original FX amount, if different ccy      |
| op_currency_code | INTEGER | Original FX currency                      |
| balance_minor    | INTEGER | Balance after tx (account-level)          |
| cashback_minor   | INTEGER | Cashback granted                          |

personal-finance проєктує тільки колонки які присутні; відсутні columns
видаються як NULL у common Transaction view.

## 4. `id` format (важливо)

`<bank>_transactions.id` має бути globally унікальний across ВСІХ
`<bank>_transactions` таблиць у БД. Це досягається префіксом:

- monobank-mcp: `mono_<api_native_id>`
- privat24-skill: `privat_<reference>` АБО `privat_h_<16-char-hash>`

`personal-finance.tx_category.tx_id` посилається на ці id, але без FK
constraint (різні parent tables). Validation - на app level у personal-finance.

## 5. Per-plugin `<bank>_accounts` (recommended shape)

| Column        | Type    | Null | Опис                                          |
|---------------|---------|------|-----------------------------------------------|
| account_id    | TEXT    | NO   | PK                                            |
| iban          | TEXT    | YES  |                                               |
| type          | TEXT    | YES  | 'card' / 'fop' / 'jar' / 'deposit' / ...      |
| currency_code | INTEGER | NO   | ISO 4217                                      |
| masked_pan    | TEXT    | YES  |                                               |
| label         | TEXT    | YES  | human label                                   |
| opened_at     | INTEGER | YES  | account creation, unix s                      |

## 6. Per-plugin schema_version

```sql
CREATE TABLE <bank>_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);
```

Кожен плагін **сам** мігрує **тільки свої** таблиці. Жоден плагін не
торкається таблиць іншого плагіна.

## 7. WAL / PRAGMA

Будь-який плагін що відкриває `~/finances/data.db` має defensively
встановлювати:

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

Безпечно повторювати - SQLite no-op якщо вже встановлено.

## 8. Як personal-finance читає

При старті MCP-сервер personal-finance робить:

```sql
SELECT name FROM sqlite_master
WHERE type='table' AND name LIKE '%_transactions'
```

Виявлені таблиці потрапляють у registry. Усі query-tools будують
UNION ALL поверх available tables, проєктуючи до common shape:

```sql
SELECT id, 'mono'   AS bank, account_id, ts, amount_minor,
       currency_code, mcc, description, counterparty, ...
  FROM mono_transactions
UNION ALL
SELECT id, 'privat' AS bank, account_id, ts, amount_minor,
       currency_code, mcc, description, counterparty, ...
  FROM privat_transactions
```

Якщо тільки одна з таблиць існує - тільки вона включається у union.
Якщо жодної - query повертає empty, personal-finance видає
friendly warning "no transaction sources detected, install at least
one ingest plugin".

## 9. Додавання нового банку

Майбутній плагін (наприклад `revolut-mcp`):

1. Дотримується цього contract: створює `revolut_accounts`,
   `revolut_transactions`, `revolut_schema_version`.
2. tx_id префіксує `revolut_<...>`.
3. Жодних змін у personal-finance не потрібно для базової роботи -
   detection runtime-based. Можливо лише оновлення description.yaml
   правил якщо бренд-specific patterns актуальні.

## 10. Версіонування contract

Цей документ версіонується. Breaking changes (видалення required column,
зміна type) - тільки через MAJOR bump і скоординований реліз усіх плагінів.
Adding new optional columns - non-breaking.

Поточна версія: **1.0**.
