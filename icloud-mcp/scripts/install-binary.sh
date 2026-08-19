#!/usr/bin/env bash
# Download the prebuilt icloud-mcp binary for the current platform, or fall
# back to a local cargo build when no release artifact is available.
#
# Invoked by hooks/hooks.json (SessionStart) and by commands/setup.md.
# Idempotent: exits 0 immediately when the binary already on disk
# reports the version in Cargo.toml. Any other binary is replaced.
#
# All informational output goes to stderr so the MCP stdio protocol stays
# clean when this script is wired into a hook.

set -euo pipefail

# The plugin manifest sets CLAUDE_PLUGIN_ROOT, but allow running standalone too.
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
BIN_DIR="${ROOT}/target/release"
BIN_PATH="${BIN_DIR}/icloud-mcp"
RELEASE_BASE="https://github.com/nikolaypavlov/claude-skills/releases/download"

log() { printf '[icloud-mcp install] %s\n' "$*" >&2; }
err() { printf '[icloud-mcp install] error: %s\n' "$*" >&2; }

# ---- read crate version ----
# Parsed BEFORE the presence check below, which needs it.
if [[ ! -f "${ROOT}/Cargo.toml" ]]; then
    err "Cargo.toml not found under ${ROOT}; cannot resolve binary version"
    exit 1
fi
version=$(grep -m1 '^version' "${ROOT}/Cargo.toml" | cut -d'"' -f2)
if [[ -z "$version" ]]; then
    err "could not parse version from Cargo.toml"
    exit 1
fi

# ---- reuse the installed binary only when it really is this version ----
# `-x` on its own is not enough, and trusting it left a Linux aarch64 ELF
# installed on a mac, where the server could not exec at all. Two ways a
# wrong binary lands here:
#   1. `/plugin update` copies the plugin directory out of the marketplace
#      clone including git-ignored files, so a `target/release/` binary left
#      behind by an old cargo fallback rides along into a NEW version dir.
#      `git pull` never removes it, so it survives every update.
#   2. A tarball built for another platform was extracted - executable by
#      permission, unable to exec (a Linux ELF sitting on a mac).
# Asking the binary for its own version catches both: a mismatch, an empty
# answer, or a failure to exec all mean "replace it". Both binaries answer
# --version before doing any other work, so the check costs milliseconds.
if [[ -x "$BIN_PATH" ]]; then
    installed=$("$BIN_PATH" --version 2>/dev/null | awk 'NR==1 {print $NF}') || true
    if [[ "$installed" == "$version" ]]; then
        log "binary already present at $BIN_PATH (v${version}); nothing to do"
        exit 0
    fi
    log "replacing binary at $BIN_PATH: found '${installed:-unusable}', want ${version}"
    rm -f "$BIN_PATH"
fi

# ---- detect platform ----
target=""
case "$(uname -s) $(uname -m)" in
    "Darwin arm64")    target="aarch64-apple-darwin" ;;
    "Darwin x86_64")   target="x86_64-apple-darwin" ;;
    "Linux x86_64")    target="x86_64-unknown-linux-gnu" ;;
    "Linux aarch64")   target="aarch64-unknown-linux-gnu" ;;
    "Linux arm64")     target="aarch64-unknown-linux-gnu" ;;
esac

# ---- try download ----
fallback_build() {
    if command -v cargo >/dev/null 2>&1; then
        log "falling back to local cargo build (this may take a few minutes)"
        ( cd "$ROOT" && cargo build --release --locked )
        return $?
    fi
    err "no prebuilt binary available for this platform and 'cargo' is not in PATH."
    err "install Rust from https://rustup.rs and re-run, or download the binary manually:"
    err "  ${RELEASE_BASE}/icloud-mcp-v${version}/"
    return 1
}

if [[ -z "$target" ]]; then
    log "platform $(uname -s) $(uname -m) has no prebuilt binary"
    fallback_build
    exit $?
fi

archive="icloud-mcp-v${version}-${target}.tar.gz"
url="${RELEASE_BASE}/icloud-mcp-v${version}/${archive}"
sha_url="${RELEASE_BASE}/icloud-mcp-v${version}/SHA256SUMS"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

log "downloading ${archive} ..."
if ! curl -fsSL "$url" -o "${tmp_dir}/${archive}"; then
    log "download failed for $url"
    fallback_build
    exit $?
fi

# ---- verify checksum (best-effort) ----
if curl -fsSL "$sha_url" -o "${tmp_dir}/SHA256SUMS" 2>/dev/null; then
    expected=$(grep " ${archive}\$" "${tmp_dir}/SHA256SUMS" | awk '{print $1}' || true)
    if [[ -n "$expected" ]]; then
        if command -v shasum >/dev/null 2>&1; then
            actual=$(shasum -a 256 "${tmp_dir}/${archive}" | awk '{print $1}')
        elif command -v sha256sum >/dev/null 2>&1; then
            actual=$(sha256sum "${tmp_dir}/${archive}" | awk '{print $1}')
        else
            log "no sha256 tool found; skipping checksum verification"
            actual="$expected"
        fi
        if [[ "$expected" != "$actual" ]]; then
            err "checksum mismatch for ${archive}"
            err "expected: $expected"
            err "actual:   $actual"
            exit 1
        fi
        log "checksum verified"
    else
        log "no entry for ${archive} in SHA256SUMS; skipping verification"
    fi
else
    log "SHA256SUMS not available; skipping verification"
fi

# ---- extract ----
mkdir -p "$BIN_DIR"
tar -C "$BIN_DIR" -xzf "${tmp_dir}/${archive}"
chmod +x "$BIN_PATH"

# ---- macOS: strip quarantine attribute so Launch Services lets the
# binary execute as a child of stdio MCP without prompting. The binary is
# not signed, so without this Gatekeeper blocks the first execution under
# LSFileQuarantineEnabled. ----
if [[ "$(uname -s)" == "Darwin" ]]; then
    xattr -d com.apple.quarantine "$BIN_PATH" 2>/dev/null || true
fi

log "installed icloud-mcp v${version} for ${target} at ${BIN_PATH}"
