# Pre-publish checklist

Manual review before tagging a release that touches the personal-finance plugin family. The threat model: the repo is public, the SQLite store is private; no API tokens, real PANs, real IBANs, real phone numbers, or real merchant data may land in the repo.

Run every section, in order. Stop on the first failure.

## 1. CI gates

```bash
# Rust crates (icloud-mcp, monobank-mcp): fmt + clippy + test
( cd icloud-mcp   && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test )
( cd monobank-mcp && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test )

# Python `uv` projects: sync + pytest + ruff
( cd privat24-skill  && uv sync && uv run pytest -q && uv run ruff check src tests fixtures )
( cd personal-finance && uv sync && uv run pytest -q && uv run ruff check src tests )

# jira-manager: import smoke (no test suite, but imports must work)
( cd jira-manager && uv sync && uv run python -c "from tools import jira_client" )
```

## 2. PII grep

We treat the repo as public. None of these patterns must hit a real value:

```bash
# Ukrainian IBAN: UA + 2 digits + 25 alphanumeric. Allowed: test fixtures
# that use obvious dummy sequences (UA0000... / UA1111... etc).
grep -rEn 'UA[0-9]{2}[A-Z0-9]{25}' \
  --include='*.py' --include='*.md' --include='*.toml' \
  --include='*.json' --include='*.yaml' --include='*.rs' --include='*.sql' .

# Ukrainian phone numbers: +380 or 380 + 9 digits.
grep -rEn '\+?380[0-9]{9}' .

# Payment card numbers: 16 digits, possibly with dashes/spaces.
# (False positives on integer literals do happen; review each hit.)
grep -rEn '\b(4[0-9]{3}|5[0-9]{3})[\ \-]?[0-9]{4}[\ \-]?[0-9]{4}[\ \-]?[0-9]{4}\b' .

# Email addresses outside the contributor allowlist.
grep -rEn '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' \
  --include='*.py' --include='*.md' --include='*.toml' \
  --include='*.json' --include='*.yaml' --include='*.rs' . \
  | grep -v 'me@nikolaypavlov\|noreply@anthropic\|dependabot\|@example\.com\|you@icloud\.com\|test@icloud\.com'
```

Expected baseline at the time PR#5 was cut:
- IBAN: two hits in `monobank-mcp/tests/` against the dummy `UA000000000000000000000000001` fixture.
- Phone: no hits.
- PAN: no hits.
- Email: no hits beyond the allowlist.

If a real PAN, IBAN, phone, or email shows up - stop and clean it up before tagging.

## 3. gitleaks

The framework runs on every commit through `.pre-commit-config.yaml`, but run it once over the whole history before a release tag to catch anything that slipped in via direct push:

```bash
brew install gitleaks   # or per the gitleaks README
gitleaks detect --source . --redact --verbose
```

Should report `no leaks found`. If it flags something, redact and force-push the affected commit before publishing (history rewrite needs explicit user authorization - never do it without).

## 4. Fixture audit

Every committed fixture must be deterministic and regenerable. No real merchants, no real account numbers, no real timestamps from your store.

```bash
# Privat24 fixture: regenerate, then diff-check
( cd privat24-skill && uv run python fixtures/generate.py )
git diff --stat privat24-skill/fixtures/

# Monobank fixture: generated at test time via fixtures/generate.rs; no
# committed binary fixtures to audit.

# Personal-finance fixtures: synthetic mono_*/privat_* tables in
# tests/conftest.py. Inline; nothing to regenerate.
```

If `git diff` shows a non-trivial fixture drift, investigate before tagging - either the generator changed (legit) or someone hand-edited the committed copy (revert).

## 5. README dry-run

Spin a clean clone and follow each plugin's setup steps top to bottom. The clean-clone smoke catches:
- README references to paths that only exist on the author's machine.
- `uv sync` failures from an out-of-date lockfile.
- Token / Keychain steps that assume prior state.

This is genuinely manual - there is no command. Block tagging until the dry-run is green.

## 6. Branch protection + signed tags

Before the actual release tag:
- `gh repo edit --enable-issues=true` (or via the web UI) - branch protection on `main`: required PR review + passing CI.
- Sign tags with a GPG key: `git config tag.gpgSign true`.
- The tag-and-push convention for `icloud-mcp` / `monobank-mcp` is documented in `CLAUDE.md` ("Rust binary plugin releases").
