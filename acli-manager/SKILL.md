---
name: acli-manager
description: This skill should be used when the user needs to manage Jira Cloud or Confluence Cloud resources using the Atlassian CLI (acli). Covers creating, searching, editing, and transitioning Jira issues, bulk operations, sprint management, board configuration, Confluence space management, and scripting workflows. Triggers include "create a Jira issue", "search Jira tickets", "manage Confluence spaces", "bulk create issues", "use acli", "run acli command", or any mention of Atlassian CLI operations.
version: 0.1.0
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

Authenticate globally with OAuth (opens browser):

```bash
acli auth login
```

Check status: `acli auth status`
Switch accounts: `acli auth switch`

## Command Structure

All commands follow the pattern: `acli <product> <resource> <action> [flags]`

Products: `jira`, `confluence`
Global flags: `--help`, `--json`, `--yes` (skip confirmation)

## Jira Operations

### Work Items (Issues)

**Create:**
```bash
acli jira workitem create --summary "Title" --project "PROJ" --type "Task"
acli jira workitem create --summary "Bug title" --project "PROJ" --type "Bug" --assignee "@me" --label "critical,backend"
acli jira workitem create --description-file desc.txt --project "PROJ" --type "Story" --parent "PROJ-100"
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
acli jira workitem search --jql "text ~ 'login'" --limit 20 --json
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
acli jira project update --key "PROJ" --description "Updated"
acli jira project archive --key "PROJ"
acli jira project delete --key "PROJ"
```

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

Most commands support: `--json` for JSON output, `--csv` for CSV (search), `--web` to open in browser.

### Quick Reference: Description Input

For work item descriptions, use Atlassian Document Format (ADF) or plain text:
- `--description "plain text"` - inline
- `--description-file desc.txt` - from file (plain text or ADF)
- `--editor` - open text editor

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

## Additional Resources

### Reference Files

- **`references/workflows.md`** - Automation workflows, bulk operation patterns, migration recipes, and scripting examples
