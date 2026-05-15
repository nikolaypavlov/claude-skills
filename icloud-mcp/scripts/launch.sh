#!/usr/bin/env bash
# Spawn the icloud-mcp server, downloading the binary first if it is missing.
#
# Claude Code invokes this from .mcp.json on every MCP child spawn. That
# happens at session start AND every /reload-plugins, so we cannot rely on
# the SessionStart hook firing first (it does not fire on reload). By
# inlining install-binary.sh here we guarantee the binary exists before the
# stdio MCP transport tries to connect to it.
#
# install-binary.sh is idempotent: if the binary is already in place it
# exits in milliseconds, so this wrapper adds essentially zero latency for
# warm starts. On a cold cache it downloads the release tarball (or falls
# back to cargo) and only then execs the binary.

set -euo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# Ensure the binary is on disk. stdout from install-binary.sh is already
# redirected to stderr, so it stays out of the MCP JSON-RPC channel.
bash "${ROOT}/scripts/install-binary.sh"

# Replace this shell with the MCP server so signals (SIGTERM from Claude
# Code shutdown) reach it directly and there is no extra process in the
# tree during normal operation.
exec "${ROOT}/target/release/icloud-mcp" "$@"
