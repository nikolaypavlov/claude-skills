# Automation Workflows and Patterns

Detailed workflows, bulk operation patterns, and scripting recipes for acli.

## Automation Workflows

### Sprint Planning Workflow

```bash
# 1. Create sprint
acli jira sprint create --name "Sprint 5" --board 10 --start 2025-02-01 --end 2025-02-14 --goal "Release v2.0"

# 2. Search backlog items
acli jira workitem search --jql "project = PROJ AND status = 'To Do' AND priority in (High, Critical)" --fields "key,summary,priority" --paginate

# 3. Bulk assign to sprint (edit labels or use transition)
acli jira workitem edit --jql "project = PROJ AND key in (PROJ-10, PROJ-11, PROJ-12)" --labels "sprint-5" --yes

# 4. Assign team members
acli jira workitem assign --key "PROJ-10" --assignee "dev1@example.com"
acli jira workitem assign --key "PROJ-11" --assignee "dev2@example.com"
```

### Bug Triage Workflow

```bash
# 1. Find unassigned bugs
acli jira workitem search --jql "project = PROJ AND type = Bug AND assignee is EMPTY AND status = Open" --fields "key,summary,priority,created"

# 2. View details of specific bug
acli jira workitem view PROJ-42 --fields "*all"

# 3. Assign and set priority
acli jira workitem assign --key "PROJ-42" --assignee "@me"
acli jira workitem edit --key "PROJ-42" --type "Bug"

# 4. Add investigation comment
acli jira workitem comment create --key "PROJ-42" --body "Investigating. Likely caused by recent auth changes in PR #234."

# 5. Transition to in progress
acli jira workitem transition --key "PROJ-42" --status "In Progress"
```

### Release Completion Workflow

```bash
# 1. Find all items in current sprint
acli jira workitem search --jql "project = PROJ AND sprint in openSprints() AND status != Done" --fields "key,summary,status,assignee"

# 2. Bulk transition completed items
acli jira workitem transition --jql "project = PROJ AND sprint in openSprints() AND status = 'In Review'" --status "Done" --yes

# 3. Add release comment to all sprint items
acli jira workitem comment create --jql "project = PROJ AND sprint in openSprints() AND status = Done" --body "Released in v2.0" --yes
```

### Daily Standup Report

```bash
# My in-progress items
acli jira workitem search --jql "assignee = currentUser() AND status = 'In Progress'" --fields "key,summary,priority"

# Items completed yesterday
acli jira workitem search --jql "assignee = currentUser() AND status changed to Done during (startOfDay(-1), endOfDay(-1))" --fields "key,summary"

# Blocked items
acli jira workitem search --jql "assignee = currentUser() AND status = Blocked" --fields "key,summary,priority"
```

## Bulk Operation Patterns

### Bulk Create from CSV

CSV format (columns: summary, projectKey, issueType, description, label, parentIssueId, assignee):

```csv
summary,projectKey,issueType,description,label,parentIssueId,assignee
Setup CI pipeline,PROJ,Task,Configure GitHub Actions,,,
Add login page,PROJ,Story,Implement OAuth login,frontend,PROJ-1,dev@example.com
Fix memory leak,PROJ,Bug,Memory grows over time,backend,,
```

```bash
acli jira workitem create-bulk --from-csv issues.csv --ignore-errors
```

### Bulk Create from JSON

Generate template first, then populate:

```bash
acli jira workitem create-bulk --generate-json > issues.json
# Edit issues.json with actual data
acli jira workitem create-bulk --from-json issues.json
```

### Bulk Edit with JQL

```bash
# Add label to all bugs in project
acli jira workitem edit --jql "project = PROJ AND type = Bug" --labels "needs-review" --yes

# Reassign all items from one user to another
acli jira workitem assign --jql "project = PROJ AND assignee = old@example.com" --assignee "new@example.com" --yes

# Bulk transition
acli jira workitem transition --jql "project = PROJ AND status = 'In Review' AND updated < -7d" --status "Done" --yes
```

### Bulk Delete / Archive

```bash
# Archive old items
acli jira workitem archive --jql "project = PROJ AND status = Done AND updated < -90d" --yes

# Delete from file list
echo "PROJ-1,PROJ-2,PROJ-3" > to-delete.txt
acli jira workitem delete --from-file to-delete.txt --yes
```

### Bulk Create Subtasks Under a Parent

**Using CLI flags (recommended):**

```bash
#!/bin/bash
PARENT="PROJ-100"
PROJECT="PROJ"

for TITLE in "Design API schema" "Implement endpoints" "Write integration tests" "Update documentation"; do
  acli jira workitem create --project "$PROJECT" --type "Sub-task" \
    --summary "$TITLE" --parent "$PARENT"
done
```

**Using `--from-json`** (when you need ADF descriptions or other fields):

```bash
# Get the numeric ID of the parent issue
PARENT_ID=$(acli jira workitem view PROJ-100 --json | jq -r '.id')

# Create subtask JSON with numeric parentIssueId
cat <<EOF > subtask.json
{
  "summary": "Design API schema",
  "projectKey": "PROJ",
  "type": "Sub-task",
  "parentIssueId": $PARENT_ID
}
EOF

acli jira workitem create --from-json subtask.json
```

> Use CLI flags for simple subtasks. Reserve `--from-json` for cases requiring ADF descriptions or fields not available as flags.

## Migration Patterns

### Clone Project Issues

> **Clone limitations**: `clone` resets status to "To Do" and drops parent-child relationships. Use it for simple copies. For full-fidelity migration (preserving status, hierarchy, ADF descriptions), see the scripting pattern below.

```bash
# Clone all epics to new project
acli jira workitem clone --jql "project = OLD AND type = Epic" --to-project "NEW" --yes --ignore-errors

# Clone specific issues
acli jira workitem clone --key "OLD-1,OLD-2,OLD-3" --to-project "NEW"

# Clone to different site
acli jira workitem clone --jql "project = OLD" --to-project "NEW" --to-site "other-site" --yes
```

### Full-Fidelity Project Migration

Script pattern for copying issues between projects preserving status, hierarchy, and ADF descriptions. Clone cannot do this -- you must view + create + transition per issue.

```bash
#!/bin/bash
# Migrate issues from SRC to DST project, preserving hierarchy, status, and ADF descriptions.
# Requires: jq
#
# Strategy:
# 1. Create epics/parents first, build old-key -> new-id map
# 2. Create child issues with parentIssueId from the map
# 3. Transition each issue to its original status

SRC="OLD"
DST="NEW"
declare -A KEY_MAP  # old key -> new key

# --- Step 1: Migrate epics (no parent) ---
for KEY in $(acli jira workitem search --jql "project = $SRC AND type = Epic" --fields "key" --csv | tail -n +2 | tr -d '"'); do
  echo "Migrating epic $KEY..."
  DATA=$(acli jira workitem view "$KEY" --json)
  SUMMARY=$(echo "$DATA" | jq -r '.fields.summary')
  STATUS=$(echo "$DATA" | jq -r '.fields.status.name')
  DESC=$(echo "$DATA" | jq '.fields.description')

  # Create in destination
  cat <<EOF > /tmp/migrate-issue.json
{
  "summary": $(echo "$SUMMARY" | jq -Rs .),
  "projectKey": "$DST",
  "type": "Epic",
  "description": $DESC
}
EOF
  NEW_KEY=$(acli jira workitem create --from-json /tmp/migrate-issue.json 2>&1 | grep -oE '[A-Z]+-[0-9]+')
  KEY_MAP[$KEY]=$NEW_KEY

  # Transition to original status
  if [ "$STATUS" != "To Do" ]; then
    acli jira workitem transition --key "$NEW_KEY" --status "$STATUS" 2>/dev/null
  fi
  echo "  $KEY -> $NEW_KEY ($STATUS)"
done

# --- Step 2: Migrate stories/tasks (with parent) ---
for KEY in $(acli jira workitem search --jql "project = $SRC AND type in (Story, Task, Bug) AND parent is not EMPTY" --fields "key" --csv | tail -n +2 | tr -d '"'); do
  echo "Migrating $KEY..."
  DATA=$(acli jira workitem view "$KEY" --json)
  SUMMARY=$(echo "$DATA" | jq -r '.fields.summary')
  STATUS=$(echo "$DATA" | jq -r '.fields.status.name')
  TYPE=$(echo "$DATA" | jq -r '.fields.issuetype.name')
  DESC=$(echo "$DATA" | jq '.fields.description')
  PARENT_KEY=$(echo "$DATA" | jq -r '.fields.parent.key')

  # Look up new parent ID
  NEW_PARENT=${KEY_MAP[$PARENT_KEY]}
  PARENT_ID=$(acli jira workitem view "$NEW_PARENT" --json | jq -r '.id')

  cat <<EOF > /tmp/migrate-issue.json
{
  "summary": $(echo "$SUMMARY" | jq -Rs .),
  "projectKey": "$DST",
  "type": "$TYPE",
  "parentIssueId": $PARENT_ID,
  "description": $DESC
}
EOF
  NEW_KEY=$(acli jira workitem create --from-json /tmp/migrate-issue.json 2>&1 | grep -oE '[A-Z]+-[0-9]+')
  KEY_MAP[$KEY]=$NEW_KEY

  if [ "$STATUS" != "To Do" ]; then
    acli jira workitem transition --key "$NEW_KEY" --status "$STATUS" 2>/dev/null
  fi
  echo "  $KEY -> $NEW_KEY ($STATUS)"
done

echo "Migration complete. ${#KEY_MAP[@]} issues migrated."
```

> Adapt the JQL queries and issue types to your project. Multi-step transitions (e.g., "To Do" -> "In Progress" -> "Done") may be required if your workflow doesn't allow direct jumps.

### Create Project from Template

```bash
# Clone project structure
acli jira project create --from-project "TEMPLATE" --key "NEWPROJ" --name "New Project" --lead-email "lead@example.com"

# Or from JSON definition
acli jira project create --generate-json > project.json
# Edit project.json
acli jira project create --from-json project.json
```

### Export Data

```bash
# Export all project issues to CSV
acli jira workitem search --jql "project = PROJ" --fields "key,summary,status,assignee,priority,type,created,updated" --csv --paginate > export.csv

# Export full JSON (search doesn't support --json, so pipe through view)
acli jira workitem search --jql "project = PROJ" --fields "key" --csv --paginate | \
  tail -n +2 | tr -d '"' | while read key; do
    acli jira workitem view "$key" --json
  done > export.json
```

### Confluence Space Setup

```bash
# Create team spaces
acli confluence space create --key "ENG" --name "Engineering" --description "Engineering documentation"
acli confluence space create --key "PM" --name "Product Management" --description "Product docs" --private

# List all spaces for audit
acli confluence space list --json --expand description,homepage
```

## Scripting Patterns

### Shell Script: Process Search Results

```bash
#!/bin/bash
# Find and process high-priority bugs

acli jira workitem search \
  --jql "project = PROJ AND type = Bug AND priority = High AND status = Open" \
  --fields "key" --csv | tail -n +2 | tr -d '"' | while read key; do
    echo "Processing $key..."
    acli jira workitem assign --key "$key" --assignee "@me"
    acli jira workitem transition --key "$key" --status "In Progress"
    acli jira workitem comment create --key "$key" --body "Auto-assigned for triage"
done
```

### Shell Script: Create Issues from Template

```bash
#!/bin/bash
# Create standard onboarding tasks for new team member

PROJECT="PROJ"
ASSIGNEE="$1"

acli jira workitem create --project "$PROJECT" --type "Task" \
  --summary "Setup development environment" --assignee "$ASSIGNEE"

acli jira workitem create --project "$PROJECT" --type "Task" \
  --summary "Complete security training" --assignee "$ASSIGNEE"

acli jira workitem create --project "$PROJECT" --type "Task" \
  --summary "Review team documentation" --assignee "$ASSIGNEE"
```

### Shell Script: Weekly Status Report

```bash
#!/bin/bash
# Generate weekly status report

PROJECT="PROJ"
echo "=== Weekly Status Report ==="

echo ""
echo "--- Completed this week ---"
acli jira workitem search \
  --jql "project = $PROJECT AND status changed to Done during (startOfWeek(), now())" \
  --fields "key,summary,assignee"

echo ""
echo "--- In Progress ---"
acli jira workitem search \
  --jql "project = $PROJECT AND status = 'In Progress'" \
  --fields "key,summary,assignee"

echo ""
echo "--- Blocked ---"
acli jira workitem search \
  --jql "project = $PROJECT AND status = Blocked" \
  --fields "key,summary,assignee,priority"
```

