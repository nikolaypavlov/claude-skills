---
name: acli-manager
description: This skill should be used when the user needs to manage Jira Cloud or Confluence Cloud resources using the Atlassian CLI (acli). Covers creating, searching, editing, and transitioning Jira issues, bulk operations, sprint management, board configuration, Confluence space management, and scripting workflows. Triggers include "create a Jira issue", "search Jira tickets", "manage Confluence spaces", "bulk create issues", "use acli", "run acli command", or any mention of Atlassian CLI operations.
version: 0.3.0
---

# Atlassian CLI (acli) Manager

Skill for managing Jira Cloud and Confluence Cloud resources using the official Atlassian CLI (`acli`). Covers CRUD operations, bulk actions, automation workflows, and cross-product tasks.

**Cloud-only**: `acli` is the official Atlassian CLI and works exclusively with Atlassian Cloud. It does not support Jira Server or Data Center. For on-premise Jira Server, the `jira-manager` skill with Python API integration handles those use cases.

## Prerequisites

### Installation

Install acli via Homebrew on macOS:

```bash
brew tap atlassian/homebrew-acli
brew install acli
```

Verify: `acli --version`

### Authentication

Auth commands are product-scoped: `acli jira auth ...` (not `acli auth ...`).

**OAuth (opens browser):**
```bash
acli jira auth login
```

**API token (headless / CI / sandboxed environments):**
```bash
echo "YOUR_API_TOKEN" | acli jira auth login --site yoursite.atlassian.net --email user@example.com --token
```

The `--token` flag is a boolean that reads the token from stdin (not a value flag).

Generate API tokens at: https://id.atlassian.com/manage-profile/security/api-tokens

Check status: `acli jira auth status`
Switch accounts: `acli jira auth switch`

## Command Structure

All commands follow the pattern: `acli <product> <resource> <action> [flags]`

Products: `jira`, `confluence`
Global flags: `--help`, `--json` (view/list commands only -- not search), `--yes` (skip confirmation)

> **Non-interactive usage**: Always pass `--yes` to multi-item modification commands (`edit`, `transition`, `delete`, `clone`, `archive` with `--jql` or comma-separated keys). Without it, commands prompt for confirmation and hang in non-interactive environments like Claude Code.

## Jira Operations

### Work Items (Issues)

**Create:**
```bash
acli jira workitem create --summary "Title" --project "PROJ" --type "Task"
acli jira workitem create --summary "Bug title" --project "PROJ" --type "Bug" --assignee "@me" --label "critical,backend"
acli jira workitem create --description-file desc.txt --project "PROJ" --type "Story" --parent "PROJ-100"  # parent can only be set at creation
acli jira workitem create --from-json workitem.json
acli jira workitem create --generate-json  # generate template
```

**View:**
```bash
acli jira workitem view KEY-123
acli jira workitem view KEY-123 --json
acli jira workitem view KEY-123 --fields "summary,status,description,comment"
acli jira workitem view KEY-123 --fields "*all"
```

**Search (JQL):**
```bash
acli jira workitem search --jql "project = PROJ" --paginate
acli jira workitem search --jql "assignee = currentUser() AND status != Done" --fields "key,summary,status"
acli jira workitem search --jql "type = Bug AND priority = High" --csv
acli jira workitem search --jql "text ~ 'login'" --limit 20
acli jira workitem search --filter 10001  # saved filter
```

**Edit:**
```bash
acli jira workitem edit --key "KEY-1" --summary "Updated title"
acli jira workitem edit --key "KEY-1,KEY-2" --assignee "user@example.com"
acli jira workitem edit --jql "project = PROJ AND status = Open" --labels "reviewed" --yes
```

**Transition:**
```bash
acli jira workitem transition --key "KEY-1" --status "In Progress"
acli jira workitem transition --key "KEY-1,KEY-2" --status "Done"
acli jira workitem transition --jql "project = PROJ AND assignee = currentUser()" --status "Done" --yes
```

**Assign:**
```bash
acli jira workitem assign --key "KEY-1" --assignee "@me"
acli jira workitem assign --key "KEY-1" --assignee "user@example.com"
acli jira workitem assign --key "KEY-1" --remove-assignee
```

**Comments:**
```bash
acli jira workitem comment create --key "KEY-1" --body "Comment text"
acli jira workitem comment create --key "KEY-1" --body-file comment.txt
acli jira workitem comment list --key "KEY-1"
```

**Links:**
```bash
acli jira workitem link create --out KEY-1 --in KEY-2 --type "Blocks"
acli jira workitem link list --key "KEY-1"
acli jira workitem link type  # list available link types
```

**Clone:**
```bash
acli jira workitem clone --key "KEY-1" --to-project "NEWPROJ"
acli jira workitem clone --jql "project = OLD AND type = Epic" --to-project "NEW" --yes
```

**Bulk Create:**
```bash
acli jira workitem create-bulk --from-json issues.json
acli jira workitem create-bulk --from-csv issues.csv
acli jira workitem create-bulk --generate-json  # generate template
```

> `create-bulk --from-csv` supports `parentIssueId` column for subtask creation but only plain text descriptions. For ADF descriptions in bulk, use `create-bulk --from-json` or loop with single `create --from-json` calls.

**Delete / Archive:**
```bash
acli jira workitem delete --key "KEY-1,KEY-2" --yes
acli jira workitem archive --key "KEY-1"
acli jira workitem unarchive --key "KEY-1"
```

### Projects

```bash
acli jira project list --paginate
acli jira project list --recent --json
acli jira project view --key "PROJ"
acli jira project create --from-project "TEMPLATE" --key "NEW" --name "New Project"
acli jira project create --from-json project.json
acli jira project create --generate-json  # generate template
acli jira project update --key "PROJ" --description "Updated"
acli jira project archive --key "PROJ"
acli jira project delete --key "PROJ"
acli jira project restore --key "PROJ"  # restore from trash
```

**Project types and issue types:**

| Project type | Default issue types | Notes |
|---|---|---|
| `software` (team-managed) | Task, Sub-task | Epic, Story, Bug require enabling in Project Settings > Features |
| `software` (company-managed) | Epic, Story, Task, Bug, Sub-task | Full set available by default |
| `service_desk` | Email request, Submit a request | No Epic/Story/Task -- not suitable for dev work |

When creating a project via `--from-json`, set `"projectTypeKey": "software"` for development projects.

Deleted projects go to trash and reserve their key. Use `acli jira project restore --key "PROJ"` to recover, or permanently delete via Jira UI (Site Administration > Deleted projects).

### Boards and Sprints

```bash
acli jira board search --project "PROJ"
acli jira board create --name "Board" --type "kanban" --filter-id 10040 --location-type "project" --project "PROJ"
acli jira board list-sprints --id 5
acli jira sprint create --name "Sprint 1" --board 5 --start 2025-01-01 --end 2025-01-14
acli jira sprint view --id 123
acli jira sprint list-workitems --id 123
```

### Filters and Dashboards

```bash
acli jira filter list
acli jira filter search --name "My Filter"
acli jira filter get --id 10001
acli jira dashboard search
```

## Confluence Operations

Currently limited to space management. Page-level operations are not yet available in the official acli.

### Spaces

```bash
acli confluence space list
acli confluence space list --type personal --json
acli confluence space list --status archived
acli confluence space create --key "TEAM" --name "Team Space" --description "Team docs"
acli confluence space create --key "PRIV" --name "Private Space" --private
acli confluence space view --id 123456 --include-all
acli confluence space update --key "TEAM" --name "New Name" --description "Updated"
acli confluence space archive --key "OLD"
acli confluence space restore --key "OLD"
```

## Common Workflows

For detailed automation workflows, bulk operation patterns, and migration recipes, consult `references/workflows.md`.

### Quick Reference: Bulk Operations

Bulk operations support multiple input methods:
- `--key "KEY-1,KEY-2,KEY-3"` - comma-separated keys
- `--jql "project = PROJ"` - JQL query targeting
- `--filter 10001` - saved filter targeting
- `--from-file issues.txt` - keys from file (comma, space, or newline separated)
- `--from-json data.json` / `--from-csv data.csv` - structured input

Add `--yes` to skip confirmation prompts. Add `--ignore-errors` to continue on failures.

### Quick Reference: Output Formats

> **`--json` support varies by command.** `view` supports `--json` and returns the raw Jira API response (including `fields.description` as ADF). `search` does **not** support `--json` -- use `--csv` or `--fields` instead. To get full JSON for search results, pipe keys through `view`: `acli jira workitem search --jql "..." --fields "key" | xargs -I{} acli jira workitem view {} --json`.

Common output flags: `--json` (view, list commands), `--csv` (search), `--fields "key,summary,status"` (search), `--web` (open in browser).

### Quick Reference: Description Input

**Plain text (no formatting):**
- `--description "plain text"` - inline, renders as unformatted text
- `--description-file desc.txt` - from file, renders as unformatted text
- `--editor` - open text editor

**Formatted descriptions (headings, bullet lists, bold):**

The `--description` and `--description-file` flags always produce plain text -- markdown, wiki markup, and ADF JSON passed through these flags will NOT render as formatted content.

For formatted descriptions, use `--from-json` with Atlassian Document Format (ADF). See `references/adf-format.md` for the full ADF reference.

Quick example -- create a work item with formatted description:

```bash
acli jira workitem create --from-json workitem.json
```

```json
{
  "summary": "My Task",
  "projectKey": "PROJ",
  "type": "Story",
  "description": {
    "type": "doc",
    "version": 1,
    "content": [
      {
        "type": "heading",
        "attrs": {"level": 3},
        "content": [{"type": "text", "text": "User Story"}]
      },
      {
        "type": "paragraph",
        "content": [{"type": "text", "text": "As a user, I want..."}]
      },
      {
        "type": "bulletList",
        "content": [
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Acceptance criterion 1"}]}]},
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Acceptance criterion 2"}]}]}
        ]
      }
    ]
  }
}
```

> **`--from-json` field name gotchas**: Use `type` (not `issueType`), and `parentIssueId` with a numeric ID (not an issue key). Get numeric ID via: `acli jira workitem view PROJ-1 --json | jq '.id'`. When debugging, use CLI flags instead of `--from-json` for clearer error messages.

To update an existing work item's description with ADF:

```bash
acli jira workitem edit --from-json edit.json --yes
```

```json
{
  "issues": ["KEY-1"],
  "description": {
    "type": "doc",
    "version": 1,
    "content": [...]
  }
}
```

Generate templates with: `acli jira workitem create --generate-json` or `acli jira workitem edit --generate-json`

### Quick Reference: JQL Patterns

Common JQL patterns for use with `--jql` flag:

| Pattern | JQL |
|---------|-----|
| My open items | `assignee = currentUser() AND status != Done` |
| Unassigned bugs | `type = Bug AND assignee is EMPTY` |
| High priority | `priority in (High, Critical, Highest)` |
| Updated recently | `updated >= -7d` |
| Created this week | `created >= startOfWeek()` |
| Text search | `text ~ "search term"` |
| Current sprint | `sprint in openSprints()` |
| Overdue items | `due < now() AND status != Done` |
| By component | `component = "Backend"` |
| Combine conditions | `project = PROJ AND type = Bug AND status = Open AND priority = High` |

## Known Limitations

- **Comment body size**: Comments have a ~32KB size limit. Exceeding it causes a `CONTENT_LIMIT_EXCEEDED` error. Workaround: split long content into multiple comments, or attach as a file instead.
- **Attachment upload**: `acli jira workitem attachment` only supports `list` and `delete` -- there is no `create` or `upload` subcommand.
- **Parent cannot be changed after creation**: There is no way to set or change a parent/epic link on an existing issue via `acli jira workitem edit`. The `--parent` flag only works on `create`. Workarounds: delete and recreate with the correct parent, or change the parent manually in the Jira UI.
- **Clone does not preserve hierarchy or status**: `acli jira workitem clone` copies issues but resets status to "To Do" and drops parent-child (epic-story) relationships. For full-fidelity project migration, see the scripting pattern in `references/workflows.md`.
- **Search does not support `--json`**: `acli jira workitem search` outputs tabular text or `--csv`. It does not accept `--json`. Use `view --json` per issue to get full JSON (including ADF descriptions).
- **Board subtask visibility**: Subtasks created via CLI may not appear on Scrum/Kanban boards until the board's filter is configured to include sub-tasks.
- **`--from-json` debugging**: Errors from `--from-json` are often generic. For easier debugging: use `--generate-json` to get the expected field names, pass `--json` to get structured error output, and prefer CLI flags over `--from-json` when possible.

## Additional Resources

### Reference Files

- **`references/workflows.md`** - Automation workflows, bulk operation patterns, migration recipes, and scripting examples
- **`references/adf-format.md`** - Atlassian Document Format (ADF) node reference for formatted descriptions
