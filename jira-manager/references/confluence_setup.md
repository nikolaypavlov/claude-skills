# Confluence Server Setup Guide

This guide explains how to set up Personal Access Token (PAT) authentication for Confluence Server / Data Center so that `tools/confluence_page.py` can read and edit pages.

## Prerequisites

- Confluence Server / Data Center 7.9 or higher (Personal Access Tokens were added in 7.9)
- A user account with view permission on the spaces you want to read, and edit permission where you want to write

To check the version without a token:

```bash
curl -s 'https://wiki.example.com/rest/applinks/1.0/manifest' | grep -o '<version>[^<]*'
```

## Step 1: Create a Personal Access Token in Confluence

1. Log in to Confluence (not Jira).
2. Click your **avatar** (top right) -> **Settings**.
3. In the left sidebar, click **Personal Access Tokens**.
4. Click **Create token**, enter a name (e.g., "Claude Code Integration") and an expiry.
5. Copy the token. You cannot see it again later.

A Jira token does not work here. On Server / Data Center every product issues its own tokens, even when Jira and Confluence share the same user directory. Confluence does not reject an unknown token: it serves the request as anonymous, so reads of public pages seem to work while private pages are missing.

## Step 2: Configure Environment Variables

Add to `~/.zshenv` (zsh) or `~/.bash_profile` (bash):

```bash
export CONFLUENCE_SERVER_URL="https://wiki.example.com"
export CONFLUENCE_API_KEY="your_confluence_token"
```

Reload the shell or open a new terminal.

## Step 3: Verify

```bash
uv run tools/confluence_page.py --test
```

Expected output: `Connected to Confluence as <username>`.

If the output says `the token was not accepted (request is anonymous)`, the token is wrong, expired or was created in Jira. Create a new one in Confluence.

## Notes

- **Storage format.** Pages are stored as XHTML with Confluence macro elements. Read with `--format storage` before you edit, and send the full edited body back. An update replaces the whole body.
- **Concurrent edits.** Pass `--expected-version N` (the version you read) to `--update`. The tool refuses to write if the page has a newer version.
- **Page width.** An update keeps the current page width (fixed or full width).
- **Token rotation.** When the token expires, `--test` reports an anonymous request. Create a new token and update `CONFLUENCE_API_KEY`.
