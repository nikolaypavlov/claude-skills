# Personal Finance: дизайн-документ

Версія: 2.1
Дата: 2026-05-20
Статус: для імплементації після ревʼю

Changelog v2.1 (від v2.0):
- **Виправлено напрямок залежностей** (Dependency Inversion). Кожен ingest-плагін
  тепер володіє ВЛАСНИМИ таблицями (`mono_*`, `privat_*`) і ВЛАСНИМИ міграціями.
  personal-finance володіє тільки `pf_*` (categorization-таблиці).
- Прибрано `pf_store` спільну Python-бібліотеку. Кожен плагін має локальний store.
- Cross-plugin shape транзакцій винесений у окремий convention-документ
  `docs/transactions-schema.md` (не enforced код, contract).
- personal-finance auto-detects available `<bank>_transactions` таблиці
  через `sqlite_master` і будує UNION ALL динамічно. Працює навіть якщо
  встановлено тільки одна з ingest-плагінів.
- `tx_category` (новa pf-table) - soft FK до tx.id з будь-якої bank-таблиці.
- Кожен плагін defensively встановлює `PRAGMA journal_mode=WAL`.

Changelog v2.0 (від v1.0):
- Розділено на три плагіни. Umbrella `personal-finance` володіє схемою і MCP query-сервером.
- monobank-mcp став slim ingest з 3 tools.
- Query/report MCP-сервер - Python (mcp SDK), не Rust.
- Multi-currency: per-currency секції у звіті, без cross-currency aggregation.
- Прибрано обмеження "мінімум 28 днів" на звіт.
- ensure_synced залишається inline але обмежений `max_wait_seconds`; cold-start backfill - окрема CLI операція.
- sync state переїхав у БД (sync_state table), не JSON.
- Privat24: один web-формат у v1, registry для майбутніх форматів.
- Dedup: external_id як primary, hash як fallback, file-sha256 в import_runs.
- monobank-mcp слідує icloud-mcp pattern 1:1 (launch.sh, install-binary.sh, GH workflow, single crate).
- Архівація CSV за import-date, не tx-date.
- Token: env-var primary, Keychain fallback.
- gitleaks enforced fail (не soft warning).

## 0. TL;DR

Три плагіни в репо claude-skills для збору і аналізу персональних фінансів локально:

- **personal-finance** (umbrella) - Python MCP-сервер з query/report tools і категоризатором. Володіє ТІЛЬКИ `pf_*` таблицями (правила і категоризація). Читає `<bank>_transactions` таблиці інших плагінів через UNION ALL з auto-detection.
- **monobank-mcp** - Rust MCP, тонкий ingest шар. Володіє `mono_*` таблицями. CLI для backfill, MCP для incremental sync і status (3 tools).
- **privat24-skill** - skill для ручного імпорту CSV з web-кабінету Privat24. Володіє `privat_*` таблицями.

Спільне SQLite-сховище `~/finances/data.db`. **Кожен плагін мігрує тільки свої таблиці**. Cross-plugin shape - convention у `docs/transactions-schema.md`. Жодних webhook, daemon чи Cloudflare Tunnel. Користувач задає Claude питання у звичайній conversation; Claude через MCP читає БД, при потребі тригерить inline sync, генерує narrative-звіт.

## 1. Цілі та антицілі

### Цілі

- Транзакції з Monobank і Privat24 в одному локальному SQLite-сховищі.
- Свіжість Monobank-даних у Claude: до 1-2 хвилин від request при невеликому gap (≤ 35 днів); CLI `monobank-mcp sync` для ручного тригера.
- Privat24 monthly import: < 2 хвилини дій користувача (export CSV -> drop у inbox -> "імпортуй приват").
- Claude може відповідати на запити типу "скільки я витратив на каву в квітні", "покажи всі перекази понад 10к за рік", "розбий витрати по категоріях за останні 90 днів", з різницею між валютами де релевантно.
- Дані ніколи не залишають локальну машину (виняток - API-виклики до Monobank та CLI/skill, що читають CSV).

### Антицілі

- Не робимо real-time Privat24 (немає API).
- Не скрапимо web-UI Privat24, не реверсимо mobile app.
- Не робимо бюджетування, прогнозування, кошториси, sharing з родиною.
- Не робимо мульти-користувацький режим. One user, one Mac, one DB.
- Не робимо UI поза CLI + Claude conversation.
- Жодних реальних даних користувача в repo.

## 2. Архітектура

### 2.1 Загальна схема

```
                       +-----------------------+
                       |  Claude Desktop       |
                       +-----+-----------+-----+
                             |           |
                  MCP stdio  |           |  MCP stdio
                             v           v
              +--------------+--+     +--+--------------------+
              | monobank-mcp    |     | personal-finance      |
              | (Rust)          |     | (Python MCP server)   |
              | owns mono_*     |     | owns pf_* (rules,     |
              |                 |     |   tx_category)        |
              | tools (3):      |     |                       |
              | - ensure_synced |     | reads mono_* and      |
              | - get_sync_     |     | privat_* via UNION    |
              |   status        |     | ALL with runtime      |
              | - list_mono_    |     | auto-detection        |
              |   accounts      |     |                       |
              |                 |     | tools (10):           |
              | CLI:            |     | - list_accounts       |
              | - backfill      |     | - get_transactions    |
              | - sync          |     | - summarize_spending  |
              | - init          |     | - find_transaction    |
              | - accounts      |     | - get_report_bundle   |
              +--------+--------+     | - set_category        |
                       |              | - add_rule            |
                       |              | - reload_rules        |
                       |              | - apply_rules_        |
                       |              |   retroactively       |
                       |              | - categorize_         |
                       |              |   uncategorized       |
                       |              +-----+----------+------+
                       |                    |          ^
                       | writes mono_*      | reads    | writes pf_*
                       v                    v          v
        +--------------+-------------------------+----+---+
        |          ~/finances/data.db (SQLite, WAL)     |
        |                                                |
        |  mono_*   (owned by monobank-mcp)              |
        |  privat_* (owned by privat24-skill)            |
        |  pf_*     (owned by personal-finance)          |
        +-----+----------------------------------+-------+
              ^                                  ^
              |                                  |
              | HTTPS pull                       | python script writes privat_*
              | (CLI backfill / ensure_synced)   |
              v                                  |
   +----------+----------+            +----------+----------+
   |  api.monobank.ua    |            |  ~/finances/inbox/  |
   +---------------------+            |  privat-*.csv       |
                                      +----------+----------+
                                                 ^
                                                 |
                                     drop manually
                                                 |
                                      +----------+----------+
                                      | user (1x/month)     |
                                      | privat24.ua/        |
                                      | statement -> CSV    |
                                      +---------------------+
```

Dependency arrows (важливо):

```
  personal-finance ----reads----> mono_*, privat_*
  (umbrella)         (knows shapes via docs/transactions-schema.md
                      convention; auto-detects available tables)

  monobank-mcp     ----writes---> mono_* only
                                  (knows nothing about pf_* чи privat_*)

  privat24-skill   ----writes---> privat_* only
                                  (knows nothing about pf_* чи mono_*)
```

### 2.2 Компоненти

| Компонент          | Тех                  | Запуск                          | Відповідальність                              |
|--------------------|----------------------|----------------------------------|-----------------------------------------------|
| personal-finance   | Python (mcp SDK)     | spawned by Claude (stdio)        | pf_* tables, query/report tools, categorizer  |
| monobank-mcp       | Rust (rmcp 1.x)      | spawned by Claude (stdio) + CLI  | mono_* tables, Monobank API ingest            |
| privat24-skill     | Markdown + Python    | invoked by Claude on request     | privat_* tables, Privat24 CSV ingest          |
| SQLite store       | sqlite3 file (WAL)   | -                                | Shared file, per-plugin table groups          |

### 2.3 Schema ownership (Dependency Inversion)

Принцип: **залежності можуть йти тільки від umbrella до ingest-плагінів, ніколи навпаки**.

- monobank-mcp володіє і мігрує тільки `mono_*` таблиці. Не знає ні про `privat_*`, ні про `pf_*`.
- privat24-skill володіє і мігрує тільки `privat_*` таблиці. Не знає про інших.
- personal-finance володіє тільки `pf_*` таблиці (categorization_rules, tx_category, category_overrides, pf_schema_version). Auto-detects `<bank>_transactions` таблиці які присутні і будує UNION ALL динамічно.

Файли:

```
monobank-mcp/schema/
  mono_001_initial.sql        creates mono_accounts, mono_transactions, mono_sync_state,
                              mono_import_runs, mono_schema_version

privat24-skill/schema/
  privat_001_initial.sql      creates privat_accounts, privat_transactions,
                              privat_import_runs, privat_schema_version

personal-finance/schema/
  pf_001_initial.sql          creates categorization_rules, tx_category,
                              category_overrides, pf_schema_version
```

**Кожен плагін мігрує тільки свої таблиці** при першому старті (або після оновлення версії). Жодне з:

- monobank-mcp не запускає DDL для `privat_*` чи `pf_*`
- privat24-skill не запускає DDL для `mono_*` чи `pf_*`
- personal-finance не запускає DDL для `mono_*` чи `privat_*`

**Per-plugin schema_version**:

```sql
CREATE TABLE <bank>_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);
```

Кожен плагін при старті:
1. Робить `CREATE TABLE IF NOT EXISTS <bank>_schema_version (...)`.
2. `SELECT MAX(version) FROM <bank>_schema_version`.
3. Якщо менше за hardcoded `EXPECTED_<BANK>_SCHEMA_VERSION` - застосовує власні файли міграцій по порядку.

**Cross-plugin shape**: convention у `docs/transactions-schema.md`. Documented, not enforced. Кожен ingest-плагін добровільно слідує. personal-finance проєктує до common Transaction shape при читанні.

**Graceful degradation**: personal-finance при старті:

```sql
SELECT name FROM sqlite_master
WHERE type='table' AND name LIKE '%_transactions';
```

Виявлені таблиці потрапляють у registry. Якщо `mono_transactions` нема (користувач не встановив monobank-mcp) - query повертає тільки privat-дані. Якщо обидвох нема - empty з friendly warning.

**WAL / PRAGMA**: кожен плагін defensively на власному connection:

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

Безпечно повторювати, SQLite no-op якщо вже встановлено.

### 2.4 Потік даних

```
Monobank cold-start (one-shot):
  user runs `monobank-mcp init` -> writes token to Keychain, creates config.toml
    -> first invocation: applies mono_001_initial.sql to ~/finances/data.db
      -> user runs `monobank-mcp backfill --from <дата>`
        -> if not provided: read /personal/client-info, use earliest account opened_at
          -> chunk into 31-day windows
            -> for each window: GET /personal/statement, sleep 61s
              -> INSERT OR IGNORE into mono_transactions
              -> UPDATE mono_sync_state (atomic per chunk)
                -> on rate limit: backoff and retry same window

Monobank incremental sync (during Claude conversation):
  Claude calls ensure_synced(max_wait_seconds=90)
    -> read mono_sync_state.last_completed_ts per account
      -> if gap == 0 or age < threshold: return {synced: true, skipped: true}
      -> else: compute chunks [last_ts, now]
        -> for each chunk while time_remaining > 60s:
           GET /personal/statement
           sleep 61s
           INSERT OR IGNORE into mono_transactions, UPDATE mono_sync_state (atomic)
        -> return {synced: true|partial, synced_through_ts, remaining_chunks}

Monobank incremental sync (manual CLI):
  user runs `monobank-mcp sync`
    -> same core logic as ensure_synced but no time budget
    -> useful when returning from vacation: do this before opening Claude

Privat24 monthly import:
  user opens privat24.ua, navigates to statement, exports CSV
    -> drag CSV to ~/finances/inbox/
      -> user tells Claude "import privat csv"
        -> Claude loads privat24-skill
          -> first invocation: applies privat_001_initial.sql
            -> python script: detect format, parse, dedup, insert into privat_transactions
              -> move file to ~/finances/archive/YYYY-MM-DD/

Categorization (on demand):
  user runs `/personal-finance:categorize` or CLI `pf-cli categorize`
    -> personal-finance auto-detects available <bank>_transactions tables
    -> for tx where id not in tx_category and id not in category_overrides:
       try categorization_rules by priority, first match wins
       INSERT INTO tx_category (tx_id, category, set_at)

Report generation (Claude conversation):
  user: "звіт за квітень"
    -> Claude calls ensure_synced (via monobank-mcp) - inline incremental
    -> Claude calls get_report_bundle(from, to) - via personal-finance MCP
       (auto-discovers mono_transactions + privat_transactions, builds UNION)
    -> Claude generates narrative report with per-currency sections
    -> Claude interactively suggests categories for uncategorized
    -> on user approval: set_category and/or add_rule via MCP tools
```

### 2.5 Шляхи і конфіги

```
~/finances/                          (data root, configurable)
  data.db                            SQLite (WAL mode)
  config.toml                        non-secret config (data_dir, sync thresholds)
  inbox/                             drop Privat24 CSVs here
  archive/
    2026-05-19/
      privat-*.csv                   moved here after import
  logs/
    monobank-mcp.log
    personal-finance.log
  rules/
    counterparty.local.yaml          gitignored, personal merchants
    overrides.local.yaml             gitignored, per-tx overrides
```

Repo-side (committed):

```
personal-finance/
  schema/
    pf_001_initial.sql               categorization_rules, tx_category,
                                     category_overrides, pf_schema_version
  rules/
    mcc.json                         generated, committed
    description.yaml                 generic global brands only
  scripts/
    build_mcc_map.py

monobank-mcp/
  schema/
    mono_001_initial.sql             mono_accounts, mono_transactions,
                                     mono_sync_state, mono_import_runs,
                                     mono_schema_version

privat24-skill/
  schema/
    privat_001_initial.sql           privat_accounts, privat_transactions,
                                     privat_import_runs, privat_schema_version
```

## 3. Модель даних

Три незалежних schema groups, по одній на плагін. Single SQLite file (`~/finances/data.db`),
але logical ownership розділений. Cross-plugin shape - convention у
`docs/transactions-schema.md`.

### 3.1 mono_* schema (owned by monobank-mcp, file: `monobank-mcp/schema/mono_001_initial.sql`)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mono_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE mono_accounts (
    account_id    TEXT PRIMARY KEY,
    iban          TEXT,
    type          TEXT,                      -- 'card' | 'fop' | 'jar' | 'deposit'
    currency_code INTEGER NOT NULL,
    masked_pan    TEXT,
    label         TEXT,
    opened_at     INTEGER                    -- unix s, from /personal/client-info
);

CREATE TABLE mono_transactions (
    id                TEXT PRIMARY KEY,      -- 'mono_' + Monobank native id
    account_id        TEXT NOT NULL,
    ts                INTEGER NOT NULL,
    amount_minor      INTEGER NOT NULL,
    currency_code     INTEGER NOT NULL,
    op_amount_minor   INTEGER,
    op_currency_code  INTEGER,
    mcc               INTEGER,
    description       TEXT,
    counterparty      TEXT,
    balance_minor     INTEGER,
    cashback_minor    INTEGER,
    raw_json          TEXT NOT NULL,
    imported_at       INTEGER NOT NULL,
    import_run_id     INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES mono_accounts(account_id),
    FOREIGN KEY (import_run_id) REFERENCES mono_import_runs(id)
);

CREATE INDEX idx_mono_tx_ts ON mono_transactions(ts);
CREATE INDEX idx_mono_tx_account ON mono_transactions(account_id, ts);
CREATE INDEX idx_mono_tx_mcc ON mono_transactions(mcc);

CREATE TABLE mono_import_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,            -- 'backfill' | 'sync'
    started_at     INTEGER NOT NULL,
    finished_at    INTEGER,
    rows_inserted  INTEGER,
    rows_skipped   INTEGER,
    error          TEXT
);

CREATE TABLE mono_sync_state (
    account_id          TEXT PRIMARY KEY,
    last_completed_ts   INTEGER NOT NULL,    -- pulled up to (exclusive)
    last_sync_at        INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES mono_accounts(account_id)
);

INSERT INTO mono_schema_version (version, applied_at)
VALUES (1, strftime('%s','now'));
```

### 3.2 privat_* schema (owned by privat24-skill, file: `privat24-skill/schema/privat_001_initial.sql`)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS privat_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE privat_accounts (
    account_id    TEXT PRIMARY KEY,           -- IBAN or masked PAN
    iban          TEXT,
    type          TEXT,
    currency_code INTEGER NOT NULL,
    masked_pan    TEXT,
    label         TEXT,
    opened_at     INTEGER
);

CREATE TABLE privat_transactions (
    id                TEXT PRIMARY KEY,       -- 'privat_<ref>' or 'privat_h_<hash16>'
    account_id        TEXT NOT NULL,
    ts                INTEGER NOT NULL,
    amount_minor      INTEGER NOT NULL,
    currency_code     INTEGER NOT NULL,
    op_amount_minor   INTEGER,
    op_currency_code  INTEGER,
    mcc               INTEGER,                -- nullable; Privat24 may not always provide
    description       TEXT,
    counterparty      TEXT,
    balance_minor     INTEGER,
    raw_json          TEXT NOT NULL,
    imported_at       INTEGER NOT NULL,
    import_run_id     INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES privat_accounts(account_id),
    FOREIGN KEY (import_run_id) REFERENCES privat_import_runs(id)
);

CREATE INDEX idx_privat_tx_ts ON privat_transactions(ts);
CREATE INDEX idx_privat_tx_account ON privat_transactions(account_id, ts);

CREATE TABLE privat_import_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL DEFAULT 'csv',
    started_at     INTEGER NOT NULL,
    finished_at    INTEGER,
    rows_inserted  INTEGER,
    rows_skipped   INTEGER,
    error          TEXT,
    file_path      TEXT,
    file_sha256    TEXT
);

CREATE INDEX idx_privat_imports_sha ON privat_import_runs(file_sha256);

INSERT INTO privat_schema_version (version, applied_at)
VALUES (1, strftime('%s','now'));
```

### 3.3 pf_* schema (owned by personal-finance, file: `personal-finance/schema/pf_001_initial.sql`)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pf_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE categorization_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    priority    INTEGER NOT NULL,            -- lower = checked first
    match_field TEXT NOT NULL,               -- 'mcc' | 'description' | 'counterparty'
    pattern     TEXT NOT NULL,               -- regex; for mcc: exact int string
    category    TEXT NOT NULL,
    enabled     INTEGER DEFAULT 1,
    created_at  INTEGER NOT NULL,
    source      TEXT NOT NULL                -- 'seed' | 'user' | 'claude-suggested'
);

CREATE INDEX idx_rules_priority ON categorization_rules(priority, enabled);

-- tx_category: result of categorizer pass. tx_id is a SOFT reference to
-- mono_transactions.id OR privat_transactions.id (no FK because parent
-- table is determined by id prefix).
CREATE TABLE tx_category (
    tx_id       TEXT PRIMARY KEY,            -- 'mono_*' or 'privat_*' or future bank prefixes
    category    TEXT NOT NULL,
    rule_id     INTEGER,                     -- FK soft to categorization_rules; NULL if manual
    set_at      INTEGER NOT NULL,
    set_by      TEXT NOT NULL                -- 'rule' | 'manual' | 'claude'
);

CREATE INDEX idx_tx_category_cat ON tx_category(category);

-- category_overrides: user manually pinning category for a specific tx,
-- bypassing rules. Higher precedence than tx_category.
CREATE TABLE category_overrides (
    tx_id     TEXT PRIMARY KEY,
    category  TEXT NOT NULL,
    note      TEXT,
    set_at    INTEGER NOT NULL
);

INSERT INTO pf_schema_version (version, applied_at)
VALUES (1, strftime('%s','now'));
```

### 3.4 Конвенції (cross-plugin)

Деталі - у `docs/transactions-schema.md`. Резюме:

- Суми - signed integer minor units. Витрата негативна, надходження додатне.
- Часи - unix seconds UTC. Локалізація в Europe/Kyiv - відповідальність шару аналізу.
- `<bank>_transactions.id` - globally унікальний, з префіксом `<bank>_`.
  - mono: `mono_<api_native_id>`
  - privat: `privat_<reference>` АБО `privat_h_<hash16>` (fallback)
- `<bank>_import_runs.file_sha256` (privat) дозволяє скіпати повторний імпорт ідентичного CSV.
- `INSERT OR IGNORE` для idempotency. Repeated backfill/sync/import - no-op на існуючих рядках.

### 3.5 Multi-currency

Усі суми зберігаються у власній валюті рахунку (`currency_code`). Cross-currency aggregation НЕ робиться при storage чи query. Доменна логіка звіту групує per currency.

Жодного `amount_uah_equivalent` поля. Це навмисно: FX-конвертація рідко стабільна historicallно (Mono rates можуть змінитись), і змішування валют як абстракція майже завжди приховує деталі що варто бачити.

### 3.6 Common Transaction view (читання personal-finance)

При query-time personal-finance проєктує per-bank таблиці до common shape:

```sql
-- Pseudocode для дискавері + проєкції
candidate_tables = SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE '%_transactions';

view_sql = "
  SELECT id, 'mono' AS bank, account_id, ts, amount_minor, currency_code,
         op_amount_minor, op_currency_code, mcc, description, counterparty,
         balance_minor, cashback_minor, raw_json, imported_at
    FROM mono_transactions
  UNION ALL
  SELECT id, 'privat' AS bank, account_id, ts, amount_minor, currency_code,
         op_amount_minor, op_currency_code, mcc, description, counterparty,
         balance_minor, NULL AS cashback_minor, raw_json, imported_at
    FROM privat_transactions
";
-- Constructed dynamically; only includes detected tables.
```

Те ж саме для `<bank>_accounts` -> common accounts view.

## 4. personal-finance (umbrella plugin, Python)

### 4.1 Структура

```
personal-finance/
  .claude-plugin/
    plugin.json
  .mcp.json                              spawns Python MCP via uv
  schema/
    pf_001_initial.sql                   ONLY pf_* tables (categorization)
  rules/
    mcc.json                             generated, committed
    description.yaml
  scripts/
    build_mcc_map.py
  server/
    pyproject.toml
    src/
      pf_server/
        __init__.py
        __main__.py                      entry point for `uv run pf-server`
        store.py                         open_db, migrate_pf, table discovery
        tools.py                         MCP tool definitions
        categorizer.py                   apply_rules() shared function
        rules.py                         rule loading + matching
        reports.py                       get_report_bundle bundling
        view.py                          dynamic UNION ALL view builder
        types.py                         TypedDict / dataclass schemas
  commands/
    categorize.md                        /personal-finance:categorize
  skills/
    personal-finance/
      SKILL.md                           monthly review entry point
  tests/
    test_store.py
    test_view_builder.py                 detection + UNION generation
    test_categorizer.py
    test_report_bundle.py
    fixtures/
      synthetic_mono_tx.json
      synthetic_privat_tx.json
```

Important: `personal-finance/schema/` contains **only** `pf_*` migrations. monobank-mcp і privat24-skill повністю незалежно мігрують свої таблиці у власних плагінах. personal-finance НЕ створює `mono_transactions` ані `privat_transactions`.

### 4.2 Залежності (pyproject.toml)

```toml
[project]
name = "pf-server"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "mcp>=1.0",                    # official Python MCP SDK
  "pyyaml>=6",
  "tomli; python_version < '3.11'",
]

[project.scripts]
pf-server = "pf_server.__main__:main"
pf-cli = "pf_server.cli:main"

[tool.uv]
managed = true
```

Stdlib для решти (sqlite3, re, json, dataclasses).

### 4.3 MCP tools (10)

| Tool                          | Args                                                                        | Returns                                                       |
|-------------------------------|-----------------------------------------------------------------------------|---------------------------------------------------------------|
| list_accounts                 | -                                                                           | array of {bank, account_id, label, currency, last_balance}    |
| get_transactions              | from_ts, to_ts, account_id?, bank?, category?, currency?, limit?, offset?   | array of Tx                                                   |
| summarize_spending            | from_ts, to_ts, group_by, account_id?, bank?, currency?                     | array of {key, total_minor, count, currency}                  |
| find_transaction              | query, limit?                                                               | array of Tx (description LIKE)                                |
| get_report_bundle             | from_ts, to_ts, account_id?, bank?, comparison?                             | bundle (see 4.4)                                              |
| set_category                  | tx_id, category, note?                                                      | success                                                       |
| add_rule                      | match_field, pattern, category, priority?, source?                          | {rule_id, would_affect_count} (preview, not applied yet)      |
| reload_rules                  | -                                                                           | {rules_count}                                                 |
| apply_rules_retroactively     | rule_id, dry_run?                                                           | {affected_count, sample}                                      |
| categorize_uncategorized      | scope? ('all' or 'last_n_days')                                             | {categorized_count, remaining_count}                          |

Group_by values: `'category' | 'mcc' | 'counterparty' | 'currency' | 'account'`.

### 4.4 get_report_bundle

Без 28-day обмеження. Прийняти будь-який період. Обмеження по обʼєму:

- Якщо `(to_ts - from_ts) <= report_full_dump_threshold_days` (default 90): повертає raw `transactions[]`.
- Якщо більше: автоматично переключається на `monthly_buckets[]` per category per currency. `transactions[]` обмежується топ-100 за абсолютною сумою + усіма uncategorized.

Bundle structure:

```jsonc
{
  "period": { "from_ts": 1745107200, "to_ts": 1747699200, "tz_hint": "Europe/Kyiv" },
  "accounts": [
    { "bank": "mono", "account_id": "...", "label": "Mono Black", "currency_code": 980 }
  ],
  "currencies_seen": [980, 840],          // ISO numeric codes present in period

  // mode == "full":
  "transactions": [
    { "id": "...", "bank": "mono", "ts": ..., "amount_minor": -25000,
      "currency_code": 980, "mcc": 5814, "description": "GLOVO",
      "counterparty": "GLOVO UA", "category": "Food/Delivery" }
  ],

  // mode == "bucketed":
  "monthly_buckets": [
    { "year_month": "2026-04", "currency_code": 980, "category": "Food/Delivery",
      "total_minor": -125000, "tx_count": 17 }
  ],
  "top_transactions": [ ... ],            // 100 largest abs(amount) for color
  "uncategorized_transactions": [ ... ],  // always full list

  "comparison": {
    "previous_period": { "from_ts": ..., "to_ts": ... },
    "per_currency": [
      { "currency_code": 980,
        "current":  { "in_minor": 1234, "out_minor": -5678, "tx_count": 45 },
        "previous": { "in_minor": ...,  "out_minor": ...,   "tx_count": ... } }
    ]
  },

  "active_rules_count": 47,
  "uncategorized_count": 8,
  "last_sync_ts": { "mono": 1747698300, "privat": 1745000000 }
}
```

`last_sync_ts` важливе - Claude може warn-ити користувача якщо дані застарілі ("остання синхронізація mono - 3 години тому").

### 4.5 Звіт - generated by Claude

Claude отримує bundle і генерує narrative-звіт. Структура (умовна, Claude може варіювати):

1. **Шапка**: період, рахунки, валюти, last_sync_ts warnings якщо є.
2. **Per-currency summary**: для кожної валюти у `currencies_seen` - total in/out, net, tx_count, vs previous period.
3. **Розбивка по категоріях**: per currency, sorted desc, %.
4. **Top контрагенти**.
5. **Recurring**: щомісячні платежі, нові підписки, зниклі.
6. **Anomalies**: великі відхилення, нові merchants у "великих" категоріях, підозрілі дублі.
7. **Uncategorized review**: інтерактивно, з пропозиціями. На user OK -> Claude викликає set_category / add_rule.
8. **Insights**: free-form prose.

### 4.6 Категоризація

Pipeline. "Uncategorized" = tx.id з common view НЕ в `tx_category` ТА НЕ в `category_overrides`.

```
       +----------------+
       | uncategorized  |     (tx not in tx_category AND
       |                |      not in category_overrides)
       +-------+--------+
               |
               v
       +-------+--------+  override exists?  +-----------+
       | category_      | -----yes---------> | apply     |
       | overrides      |                    | (no-op,   |
       +-------+--------+                    |  override |
               | no                          |  wins)    |
               v                             +-----------+
       +-------+--------+   mcc match   +-------------+
       | mcc rules      | ------------> | INSERT INTO |
       +-------+--------+               | tx_category |
               | no match               +-------------+
               v
       +-------+--------+   match       +-------------+
       | counterparty   | ------------> | INSERT INTO |
       +-------+--------+               | tx_category |
               | no match               +-------------+
               v
       +-------+--------+   match       +-------------+
       | description    | ------------> | INSERT INTO |
       +-------+--------+               | tx_category |
               | no match               +-------------+
               v
       +----------------+
       | no row in      |
       | tx_category,   |
       | surface in     |
       | report flow    |
       +----------------+
```

Rules:
- `priority` ASC: lower number checked first.
- Перший match - перемагає, INSERT у `tx_category` з rule_id reference і `set_by='rule'`.
- `category_overrides` має пріоритет над `tx_category` при query (manual user decision wins).
- При query (e.g., get_transactions) category resolution:
  `COALESCE(category_overrides.category, tx_category.category, NULL)`.

Джерела правил:

| Файл                                      | Походження                          | Commit? |
|-------------------------------------------|-------------------------------------|---------|
| `personal-finance/rules/mcc.json`         | `scripts/build_mcc_map.py`          | yes     |
| `personal-finance/rules/description.yaml` | generic global brands (Apple, Google, Uber, ...) | yes     |
| `~/finances/rules/counterparty.local.yaml` | local merchants by name             | NO      |
| `~/finances/rules/overrides.local.yaml`   | per-tx overrides                    | NO      |

`build_mcc_map.py` parses PrivatBank MCC PDF за default; з `--source mcc.in.ua` оновлює з web. Output - committed `rules/mcc.json` (50-150 кодів покривають 95% побутових категорій).

### 4.7 add_rule з preview

Коли Claude через `add_rule` пропонує нове правило, tool НЕ застосовує одразу. Повертає:

```json
{
  "rule_id": 42,
  "would_affect_count": 18,
  "sample": [
    { "id": "tx1", "description": "...", "ts": ... },
    ... // up to 5
  ],
  "applied": false
}
```

Claude показує користувачу: "правило торкнеться 18 транзакцій. Приклади. Застосувати ретроактивно?" Якщо user-yes - Claude викликає `apply_rules_retroactively(rule_id=42, dry_run=false)`. Якщо ні - rule залишається в БД для майбутніх імпортів, але старі рядки не torkanyi.

### 4.8 Тести

- `test_store.py`: open in-memory, migrate, schema_version reads correctly.
- `test_categorizer.py`: synthetic transactions, kожне правило по черзі, override precedence.
- `test_report_bundle.py`: full mode vs bucketed mode auto-switch, comparison correctness, per-currency split.
- pytest, без external deps.

## 5. monobank-mcp (Rust, slim ingest)

### 5.1 Чому Rust і чому MCP

- **Rust**: один статичний бінарь, fast cold start (важливо бо spawned per Claude session).
- **MCP**: stateless lifecycle добре пасує до spawn-per-session model.
- **Slim**: тільки ingest. Query - в umbrella.

### 5.2 Структура (копія icloud-mcp pattern)

```
monobank-mcp/
  Cargo.toml                            single crate, NOT workspace
  rustfmt.toml
  .mcp.json
  .gitignore
  schema/
    mono_001_initial.sql                OWN migrations for mono_* tables
  src/
    main.rs                             clap dispatch
    config.rs                           toml + env + Keychain
    types.rs
    api.rs                              reqwest client for api.monobank.ua
    store.rs                            rusqlite, applies own migrations,
                                        INSERT OR IGNORE into mono_transactions
    migrations.rs                       embeds schema/*.sql via include_str!,
                                        applies to mono_schema_version
    backfill.rs                         chunked, resumable
    sync.rs                             core sync, shared by CLI and MCP
    error.rs
    mcp/
      mod.rs                            stdio server
      tools.rs                          3 tools (ensure_synced, get_sync_status, list_mono_accounts)
    util/
      ratelimit.rs                      token bucket 1 req / 60s
      time.rs                           chrono helpers
  scripts/
    launch.sh                           copied from icloud-mcp
    install-binary.sh                   copied from icloud-mcp
  hooks/
    hooks.json                          SessionStart pre-warm
  commands/
    setup.md                            /monobank-mcp:setup
  tests/
    api_mock.rs
    store_roundtrip.rs
    migrations.rs                       fresh DB -> migrate -> verify schema
    backfill_resume.rs
    sync_resume.rs
    mcp_tools.rs
  fixtures/
    generate.rs                         seeded RNG for API responses
```

monobank-mcp при старті завжди робить:

```rust
// store.rs init sequence
conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
ensure_mono_schema(&conn)?;   // creates mono_schema_version if missing,
                              // applies migrations up to EXPECTED_MONO_SCHEMA_VERSION
```

Це означає: користувач може встановити лише monobank-mcp і він повністю самодостатній.
Будь-який ingest працює без personal-finance плагіну. personal-finance потрібен тільки
для query/report/categorization.

GitHub workflow `.github/workflows/release-monobank-mcp.yml` копіюється з `release-icloud-mcp.yml` з відповідними змінами назв.

### 5.3 Залежності

Дзеркало icloud-mcp:

```toml
[dependencies]
rmcp = { version = "1.7", features = ["server", "macros", "transport-io"] }
tokio = { version = "1", default-features = false, features = [
    "rt-multi-thread", "macros", "io-std", "io-util", "net", "time", "sync"
] }
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls"] }
rusqlite = { version = "0.32", features = ["bundled"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
schemars = { version = "1", features = ["chrono04"] }
chrono = { version = "0.4", features = ["serde"] }
clap = { version = "4", features = ["derive"] }
anyhow = "1"
thiserror = "1"
tracing = "0.1"
tracing-subscriber = "0.3"
tracing-appender = "0.2"
keyring = "3"
toml = "0.8"
sha2 = "0.10"
```

### 5.4 CLI

```
monobank-mcp <subcommand>

  init                       configure (token in Keychain or env), write config.toml
  accounts                   list accounts via /personal/client-info, sync to DB
  backfill                   cold-start backfill
    --from <date>            optional; default: earliest account opened_at
    --to <date>              default: now
    --account <id>           default: all
  sync                       manual incremental sync (no time budget)
    --account <id>           default: all
  serve                      run MCP server on stdio (used by Claude Desktop)
  query                      debug: invoke a tool from CLI
    --tool <name>
    --args <json>
```

### 5.5 MCP tools (3)

| Tool                | Args                                                | Returns                                                               |
|---------------------|-----------------------------------------------------|-----------------------------------------------------------------------|
| ensure_synced       | max_wait_seconds? (default 90), account_id?         | {synced, skipped, partial, synced_through_ts, remaining_chunks, rows_added} |
| get_sync_status     | account_id?                                         | array of {bank, account_id, last_completed_ts, gap_seconds, last_sync_at} |
| list_mono_accounts  | -                                                   | array of mono accounts (for setup debugging)                          |

Note: `list_accounts` живе у `personal-finance` і повертає ВСІ рахунки. `list_mono_accounts` тут потрібен тільки для діагностики setup ("чи бачить mono mcp мій рахунок взагалі").

### 5.6 ensure_synced flow

```
ensure_synced(max_wait_seconds=90, account_id=None):
    start = now()
    deadline = start + max_wait_seconds
    
    accounts = account_id ? [account_id] : all_mono_accounts()
    rows_added_total = 0
    remaining_chunks_total = 0
    
    for acc in accounts:
        last_ts = sync_state.last_completed_ts[acc]  // 0 if no entry
        if last_ts == 0:
            return {error: "no backfill yet, run `monobank-mcp backfill` first"}
        
        chunks = chunk_31d(last_ts, now())
        for i, (from, to) in enumerate(chunks):
            if now() + 60 > deadline:
                remaining_chunks_total += len(chunks) - i
                break
            
            rate_limit_wait()  // sleep until 60s since last request
            resp = api.statement(acc, from, to)
            with conn.transaction():
                rows_added = insert_or_ignore(resp)
                sync_state.update(acc, last_completed_ts=to)
            rows_added_total += rows_added
    
    partial = remaining_chunks_total > 0
    return {
        synced: !partial,
        partial,
        skipped: rows_added_total == 0 && remaining_chunks_total == 0,
        synced_through_ts: ...,
        remaining_chunks: remaining_chunks_total,
        rows_added: rows_added_total,
    }
```

Key invariants:
- Per-chunk atomic commit (INSERTs + sync_state.update в одній SQLite transaction).
- Якщо tool вбито посеред chunk - наступний виклик resume-ить з last_completed_ts.
- Якщо rate limit hit (429) - exponential backoff inside this chunk, до 3 retry.

### 5.7 Backfill flow

```
backfill --from <date> [--account ...]:

  +-------------+
  |   start     |
  +------+------+
         |
         v
  +------+------------+
  | enumerate accounts|
  | (or use --account)|
  +------+------------+
         |
         v
  +------+------------+
  | from = arg.from   |
  | or accounts'      |
  | opened_at         |
  +------+------------+
         |
         v
  +------+------------+
  | compute 31-day    |
  | chunks [from,now] |
  +------+------------+
         |
         v
  +------+------------+
  | next chunk?       |--no--> done
  +------+------------+
         | yes
         v
  +------+------------+
  | rate_limit_wait   |
  +------+------------+
         |
         v
  +------+------------+
  | GET /statement    |
  +------+------------+
         |
   +-----+------+
   | status?    |
   +--+--+-+----+
      |  | |
    200 429 5xx
      |  | |
      |  | +--> sleep 60s, retry
      |  +-----> sleep 90s, retry same chunk (up to 3)
      |
      v
  +------+-------------+
  | tx (INSERT, update |
  |  sync_state)       |
  +------+-------------+
         |
         v
   (loop)
```

Backfill ідемпотентний через INSERT OR IGNORE. SIGINT mid-backfill безпечний - state persists per chunk.

### 5.8 Token storage

Priority order:
1. `MONOBANK_TOKEN` env var (highest)
2. Keychain (`service=monobank-mcp, account=api-token`)
3. Fail with clear message instructing to run `monobank-mcp init`

`init` command:
- Prompts for token
- Writes to Keychain if available, falls back to instructing user to set env var
- Writes `config.toml` with `token_in_keychain = true|false` flag

`config.toml` is non-secret, can live anywhere; default `~/finances/config.toml`.

### 5.9 Збірка і встановлення

Стандарт icloud-mcp:

```bash
# Plugin install (user-facing):
# 1. install personal-finance plugin (required dep)
# 2. install monobank-mcp plugin
# 3. в Claude Desktop або Code: SessionStart hook фає install-binary.sh,
#    яка завантажує prebuilt artifact з GitHub Releases або builds локально
# 4. /monobank-mcp:setup - interactive token capture
# 5. monobank-mcp backfill --from 2024-01-01 (one-time)

# Dev install:
cd monobank-mcp && cargo build --release
ln -s "$PWD/target/release/monobank-mcp" /usr/local/bin/monobank-mcp
```

`.mcp.json`:

```jsonc
{
  "mcpServers": {
    "monobank": {
      "command": "${CLAUDE_PLUGIN_ROOT}/scripts/launch.sh",
      "args": []
    }
  }
}
```

### 5.10 Тести

- `tests/api_mock.rs` - wiremock, synthetic API responses з `fixtures/generate.rs`.
- `tests/store_roundtrip.rs` - in-memory rusqlite, schema apply, INSERT OR IGNORE idempotency.
- `tests/backfill_resume.rs` - simulate kill mid-backfill, verify resume.
- `tests/sync_resume.rs` - simulate ensure_synced interruption mid-chunk.
- `tests/mcp_tools.rs` - кожен tool з valid/invalid args.

### 5.11 Що НЕ робить monobank-mcp

- Не категоризує (це personal-finance).
- Не робить query / report (це personal-finance).
- Не приймає webhook (pull-only).
- Не утримує daemon (lifecycle = Claude session чи CLI invocation).
- Не торкається таблиць інших плагінів (`privat_*`, `pf_*`). Свої `mono_*`
  таблиці monobank-mcp мігрує самостійно (див. §2.3, §3.1).

## 6. privat24-skill

### 6.1 Структура

```
privat24-skill/
  .claude-plugin/
    plugin.json
  schema/
    privat_001_initial.sql              OWN migrations for privat_* tables
  skills/
    privat24-import/
      SKILL.md
      parsers/
        __init__.py
        detect.py                       format sniffing
        web.py                          web кабінет (v1)
        # mobile.py, fop.py             stubs for later
      fixtures/
        generate.py                     seeded RNG generator
        sample_web.csv                  GENERATED, committed
      lib/
        __init__.py
        store.py                        sqlite3 open + apply privat_* migrations
        dedup.py                        hashing + external_id detection
      tests/
        test_detect.py
        test_parse_web.py
        test_dedup.py
        test_integration.py
        test_migrations.py
  examples/
    workflow.md
```

**Жодної залежності від personal-finance**. `lib/store.py` - локальний код у самому skill,
читає `schema/privat_001_initial.sql` (relative до SKILL.md location) і застосовує до
`~/finances/data.db`. Skill працює standalone (інгест працює, але query/report - тільки
якщо personal-finance встановлено).

```python
# lib/store.py (sketch)
def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")
    ensure_privat_schema(conn)
    return conn

def ensure_privat_schema(conn):
    # idempotent: CREATE TABLE IF NOT EXISTS privat_schema_version
    # then read privat_schema_version, apply needed migrations
    ...
```

### 6.2 v1 формат: privat24.ua/statement (web)

Що очікую (буде уточнено з твого реального sample-header, без даних):

- Кодування: utf-8 with BOM, потенційно cp1251 fallback.
- Розділювач: `;`.
- Заголовки приблизно: `Дата;Час;Категорія;Опис;Сума;Валюта;Сума в валюті картки;Валюта картки;Залишок;Номер карти;Референс`.
- Реальний sample headers - попрошу окремо перед PR#3.

### 6.3 Дедуплікація

```python
def tx_id_for_privat(row, file_sha256, row_idx, account_id) -> str:
    if row.get('reference'):
        return f"privat_{row['reference']}"
    digest = sha256(
        f"{row['ts']}|{row['amount_minor']}|{row['description'][:80]}|"
        f"{account_id}|{file_sha256[:8]}|{row_idx}".encode()
    ).hexdigest()[:16]
    return f"privat_h_{digest}"
```

INSERT OR IGNORE into `privat_transactions(id, ...)`. `privat_import_runs.file_sha256`
дозволяє skip-ити повторний імпорт ідентичного файлу одразу - перед парсингом.

### 6.4 SKILL.md (skeleton)

```markdown
---
name: privat24-import
description: |
  Use this skill when the user asks to import a Privat24 statement,
  mentions a CSV from PrivatBank or Privat24, says "imp privat",
  "оновити приват", "залий новий csv з привату", or references files
  matching ~/finances/inbox/privat*.csv. Standalone - does not depend
  on other finance plugins.
allowed-tools: Bash, Read, Write, Edit
---

# Privat24 CSV import skill

## When invoked
User wants to ingest a freshly exported Privat24 web statement.

## Steps
1. Open `~/finances/data.db` via lib/store.py (creates and migrates
   privat_* tables if missing - self-contained).
2. List candidates in `~/finances/inbox/`. Confirm if ambiguous.
3. For each file:
   - Compute file_sha256; skip if file_sha256 already in
     privat_import_runs.
   - Run parsers/detect.py. If unknown, ask user for sample.
   - Run matching parser.
   - For each row, compute tx_id (external_id preferred, hash fallback).
   - INSERT OR IGNORE into privat_transactions. Update privat_import_runs.
4. Move file to ~/finances/archive/YYYY-MM-DD/ (today's date).
5. Report counts to user.

## What NOT to do
- Do not categorize (no access to pf_* tables - that is personal-finance's job).
- Do not write to mono_* tables.
- Do not delete source CSV. Only move to archive.
- Do not touch non-Privat accounts.
```

### 6.5 Тести

Усі на synthetic fixtures (`fixtures/generate.py`, seeded RNG). Жодного real CSV.

## 7. План імплементації (PRs)

Порядок змінено: оскільки три плагіни тепер незалежні у схемі, monobank-mcp і privat24-skill можна писати у будь-якій послідовності, але personal-finance природно йде ОСТАННІМ (бо його тести легше валідувати коли є реальні `<bank>_transactions` таблиці від ingest-плагінів).

### PR #1: monobank-mcp (slim ingest)

Goal: full Rust ingest, copies icloud-mcp pattern 1:1. Standalone.

- `Cargo.toml`, `rustfmt.toml`
- `schema/mono_001_initial.sql`
- `src/`:
  - `main.rs`, `config.rs`, `types.rs`, `api.rs`, `error.rs`
  - `store.rs` - opens DB, runs `ensure_mono_schema()`, INSERTs to `mono_*`
  - `migrations.rs` - embeds SQL via `include_str!`, applies up to `EXPECTED_MONO_SCHEMA_VERSION`
  - `backfill.rs`, `sync.rs`
  - `mcp/{mod.rs, tools.rs}` - 3 tools
  - `util/{ratelimit.rs, time.rs}`
- `scripts/launch.sh`, `scripts/install-binary.sh` (copied from icloud-mcp)
- `hooks/hooks.json`
- `commands/setup.md`
- `.mcp.json`
- `tests/`: api_mock, store_roundtrip, migrations, backfill_resume, sync_resume, mcp_tools
- `fixtures/generate.rs`
- `.github/workflows/release-monobank-mcp.yml`
- `.github/dependabot.yml` updated
- marketplace.json: додати entry

Acceptance: `cargo build --release` clean (clippy + fmt). Fresh empty DB -> `monobank-mcp backfill` creates schema and pulls data. `cargo test` зелений на synthetic fixtures. Working standalone без інших плагінів.

### PR #2: privat24-skill (standalone CSV ingest)

Goal: web-format import. Standalone.

- `.claude-plugin/plugin.json`
- `schema/privat_001_initial.sql`
- `skills/privat24-import/`:
  - `SKILL.md`
  - `parsers/{__init__, detect, web}.py`
  - `lib/{__init__, store, dedup}.py`
  - `fixtures/generate.py` + committed `sample_web.csv` (generated)
  - `tests/test_*.py` including test_migrations.py
- marketplace.json: додати entry

Acceptance: pytest зелений. Manual test: fresh empty DB, drop generated sample CSV у inbox, "імпортуй приват" в Claude, schema створюється + rows у `privat_transactions`, file moves to archive. Working standalone без інших плагінів.

Before PR #2 starts: попрошу real sample headers (без даних) і edge case examples (FX rows, refunds, holds).

### PR #3: personal-finance skeleton

Goal: scaffold umbrella plugin, table discovery, MCP server skeleton.

- `.claude-plugin/plugin.json`
- `schema/pf_001_initial.sql` (categorization_rules, tx_category, category_overrides, pf_schema_version)
- `server/pyproject.toml` (uv-managed, mcp SDK, pyyaml)
- `server/src/pf_server/`:
  - `__main__.py` - stdio MCP entry
  - `store.py` - open_db, migrate_pf (own tables only)
  - `view.py` - discovers `<bank>_transactions` via sqlite_master, builds UNION ALL SQL
  - `tools.py` - skeleton з list_accounts, get_transactions працюючими через dynamic view
  - `types.py`
- `.mcp.json` що spawn-ить `uv run pf-server`
- `commands/categorize.md` - stub
- `skills/personal-finance/SKILL.md` - stub з тригерами
- `tests/test_store.py`, `test_view_builder.py`
- marketplace.json: додати entry
- README

Acceptance: 
- `uv run pf-server` стартує
- На empty DB - friendly warning "no transaction sources detected"
- На DB де є тільки `mono_transactions` (з PR#1) - list_accounts повертає mono акаунти; get_transactions повертає тільки mono рядки
- На DB де є тільки `privat_transactions` - аналогічно
- На DB з обома - UNION ALL працює коректно

### PR #4: personal-finance tools fleshed out

Goal: complete MCP tool surface, categorizer, mcc-map generator.

- `server/src/pf_server/`:
  - `categorizer.py` - apply_rules() writing to tx_category
  - `rules.py` - load + match logic, local override yaml loader
  - `reports.py` - build_report_bundle() (full + bucketed, per-currency)
  - `tools.py` - all 10 tools implemented
- `scripts/build_mcc_map.py` (parse PrivatBank PDF або mcc.in.ua HTML)
- `rules/mcc.json` (generated, committed)
- `rules/description.yaml` (seed з 20-30 global brands)
- `commands/categorize.md` - filled out
- `tests/test_categorizer.py`, `test_report_bundle.py`, `test_rules.py`
- CI integration test: spin up clean DB, apply mono migrations (PR#1), apply privat migrations (PR#2), apply pf migrations, run categorize, assert tx_category populated. Validates cross-plugin shape convention.

Acceptance: end-to-end synthetic test: insert 50 transactions across mono+privat, categorize, generate report bundle, validate per-currency split.

### PR #5: polish

- Per-plugin README (3 files)
- Sample launchd plist (backup option for hourly sync; opt-in)
- Sample backup script (`scripts/backup_db.sh` - rclone target generic)
- `.gitignore` updates
- Pre-commit config (`.pre-commit-config.yaml` з gitleaks, detect-secrets, custom no-pii check)
- Pre-publish checklist run з results
- Update top-level CLAUDE.md з новими плагінами

## 8. Ризики і відкриті питання

### Ризики

- **Privat24 змінить web CSV формат**: mitigation - registry of parsers, new file per version.
- **Monobank rate limit жорсткіший за документований**: mitigation - configurable interval в config.toml, exponential backoff.
- **Inline ensure_synced упирається у Claude Desktop tool timeout**: mitigation - max_wait_seconds default 90s (safely within typical limits), partial response заохочує Claude питати користувача чи продовжити.
- **macOS Keychain GUI prompt блокує MCP startup**: mitigation - env-var primary path, Keychain опціональна.
- **Multi-currency без cross-currency aggregation робить total spending дивним**: за дизайном; per-currency сектори чесніші ніж conversion noise.
- **Cross-plugin shape drift**: ingest-плагіни добровільно слідують `docs/transactions-schema.md` convention. Якщо один з них додасть/видалить required column - personal-finance проєкція може зламатися. Mitigation:
  - CI integration test (PR#4) запускає всі міграції разом + assertion на проєкцію.
  - `docs/transactions-schema.md` версіонується; breaking changes - тільки через MAJOR bump усіх плагінів.
  - В personal-finance `view.py` defensively `COALESCE(<col>, NULL)` для optional columns.
- **Один плагін викликаний без іншого**: за дизайном працює. Кожен ingest standalone; personal-finance gracefully degrades.

### Відкриті питання

- **Privat24 web CSV exact headers**: попрошу sample headers перед PR#3.
- **MCC seed: PrivatBank PDF vs mcc.in.ua**: vendor in PDF as authoritative seed, generator має `--source mcc.in.ua` для refresh. Default = PDF.
- **Currency rate-fetching**: НЕ робимо у v1. Якщо знадобиться cross-currency analysis - окремий future plugin.
- **add_rule retroactive default**: pendant question - чи питати юзера в Claude flow, чи робити "preview then ask"? Дизайн: завжди preview + ask. Не auto-apply.
- **Backup destination**: out of scope для коду, sample script як reference.

### Що знадобиться від користувача

**Для коду в публічному repo (інженеру):**
1. Privat24 web CSV headers (без даних) + опис edge cases.
2. Підтвердження що Monobank API docs - офіційні (https://api.monobank.ua/docs/).
3. Cross-plugin convention (`docs/transactions-schema.md`) - інженер слідує і не порушує без MAJOR bump.

**Локально на машині користувача:**
1. Personal Monobank API token (через api.monobank.ua).
2. Privat24 CSV - кладуться в `~/finances/inbox/`, обробляються локально.
3. Claude Desktop або Code з трьома плагінами (мінімум: один ingest + personal-finance).
4. Optional: `~/finances/rules/counterparty.local.yaml` з personal merchants.

## 9. Публічність репозиторію і захист PII

Без змін від v1.0 - дизайн повністю переноситься. Резюме для повноти:

### 9.1 Що НІКОЛИ не комітиться

- Token / credentials.
- `config.toml`.
- `data.db`, journal/wal/shm.
- `~/finances/inbox/`, `archive/`, `logs/`.
- Реальні CSV навіть "sanitized".
- `*.local.*` файли.
- IBAN, PAN, phone numbers, emails реальних осіб.

### 9.2 Fixtures - fully synthetic, generated

- `personal-finance/tests/fixtures/synthetic_tx.json` - seeded
- `monobank-mcp/fixtures/generate.rs` - seeded RNG, generic merchants
- `privat24-skill/skills/privat24-import/fixtures/generate.py` - seeded, generic
- Усі generators committed; outputs committed; reproducibility гарантована.
- `python|cargo run --verify` mode - sanity check на жодного real merchant у whitelist.

### 9.3 Defaults: жодних особистих

- No tokens у repo.
- Generic author placeholder для public files (специфічно: monobank-mcp Cargo.toml має `authors = ["Mykola Pavlov <me@nikolaypavlov.com>"]` - personal email є в icloud-mcp і не вважається PII у контексті open source maintenance; threat model тут - leak фінансових даних, не identity).

### 9.4 Logging redaction

INFO default. amount_minor, description, counterparty REDACTED на INFO+. TRACE - окремий файл, opt-in, з warning у README.

### 9.5 .gitignore (мінімум)

```
/target
__pycache__/
*.pyc
.pytest_cache/
.venv/
config.toml
data.db
data.db-journal
data.db-wal
data.db-shm
inbox/
archive/
logs/
*.local.*
*.local
.env
.envrc
.DS_Store
.idea/
.vscode/
```

### 9.6 Pre-commit hooks

- gitleaks - HARD FAIL (not soft warning, як було в v1).
- detect-secrets - second opinion.
- Custom `scripts/check_no_pii.sh`:
  - PAN regex
  - IBAN UA regex
  - Phone UA regex
  - Email
  - Cyrillic merchants outside approved synthetic list
  - Absolute user-homedir paths

### 9.7 CI

- `cargo build && cargo test && cargo clippy -D warnings && cargo fmt --check` для monobank-mcp.
- `uv run pytest` для personal-finance і privat24-skill.
- pre-commit run on full tree.
- `cargo audit` для CVE.
- Secret-scanning enabled in GitHub repo settings.

### 9.8 Pre-publish checklist

- `git log --all --full-history` - переглянути.
- grep на real phone / email / names.
- IBAN-pattern / PAN-pattern search.
- Усі fixtures from generator.
- Cargo.toml emails generic-ish (single maintainer email OK, але не дублі).
- README без real account types / specific banks branding.
- One dry-run: clean clone, builds, fails з ясним setup-instruction.
- gitleaks clean.

## Додаток A: посилання

- Monobank Personal API: https://api.monobank.ua/docs/
- Model Context Protocol: https://modelcontextprotocol.io
- rmcp Rust SDK: https://github.com/modelcontextprotocol/rust-sdk
- mcp Python SDK: https://github.com/modelcontextprotocol/python-sdk
- ISO 4217: https://www.iso.org/iso-4217-currency-codes.html
- MCC codes (Ukraine, authoritative): https://static.privatbank.ua/files/0000003951391200.pdf
- MCC codes (Ukraine, browsable): https://mcc.in.ua/
- MCC list (global fallback): https://github.com/greggles/mcc-codes
- gitleaks: https://github.com/gitleaks/gitleaks
- detect-secrets: https://github.com/Yelp/detect-secrets
- icloud-mcp (reference pattern in this repo): ../icloud-mcp/

## Додаток B: чекліст готовності до production

**Functional:**
- [ ] personal-finance плагін встановлено, MCP сервер відповідає
- [ ] `monobank-mcp init` запущено, token у Keychain
- [ ] `monobank-mcp backfill --from <дата>` завершено
- [ ] У Claude: "список рахунків" -> працює
- [ ] У Claude: "звіт за минулий місяць" -> ensure_synced + report bundle працюють
- [ ] privat24-skill встановлено, sample import успішний
- [ ] `/personal-finance:categorize` запускається і коректно класифікує seed rules
- [ ] Sample backup script відпрацював на копії БД

**Security локально:**
- [ ] `data.db` на encrypted volume (FileVault)
- [ ] Token не у repo, тільки Keychain або env
- [ ] `~/finances/` має 700 permissions

**Public repo (перед першим push, далі - per-PR):**
- [ ] Pre-publish checklist 9.8 пройдено
- [ ] CI зелений
- [ ] Secret-scanning enabled
- [ ] Public README не містить real user setup
- [ ] Branch protection на main: PR review + passing CI
