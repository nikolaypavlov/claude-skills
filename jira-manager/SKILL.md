---
name: jira-manager
description: Generate Jira ticket content for small development teams using Kanban workflow. Use when creating bugs, tasks, stories or epics with proper templates and structure.
---

# Jira Manager

Skill for generating structured Jira ticket content for small development teams using Kanban workflow.

## Process

1. **Determine ticket type** from user request
2. **Determine language**:
   - Use language explicitly requested by user
   - If not specified, use the language of conversation with user
3. **Read appropriate template** from `reference/ticket_templates.md`
4. **Gather required information** through conversation:
   - Summary (following template format)
   - Description details (structured per template)
   - Component name
5. **Generate formatted ticket content** ready to copy-paste into Jira
6. **Create ticket in Jira** (optional):
   - If user wants to create ticket directly in Jira Server
   - Use `tools/create_ticket.py` to create via API
   - If no configuration exists, setup wizard will run automatically
   - Returns issue key and URL

## Configuration

### Jira Server API Integration

The skill supports direct integration with Jira Server v9.12+ using Personal Access Tokens (PAT).

**Configuration File**: `~/.config/jira/config.toml`

**Per-Directory Profiles**: Each project directory can have its own Jira configuration (server, project, credentials).

**First-Time Setup**: When you first try to create a ticket via API, an interactive setup wizard will run:
- Prompts for Jira Server URL
- Prompts for Personal Access Token
- Prompts for default Project Key
- Tests connection
- Saves configuration for current directory

**Multiple Jira Servers**: You can configure different Jira servers and projects for different directories.

## Requirements

### Python Dependencies

For API integration features (creating/updating tickets directly in Jira), Python tools require the following dependencies:

**Python Version**: 3.10 or higher

**Install dependencies**:

**Option 1: Using uv run (recommended - automatic dependency management)**:

If `uv` is available, use `uv run` to automatically handle dependencies:

```bash
cd /path/to/jira-manager

# No installation needed! uv run handles everything
uv run tools/create_ticket.py
uv run tools/update_ticket.py
uv run tools/setup_wizard.py
```

**Option 2: Using uv with explicit venv (for persistent environment)**:

```bash
cd /path/to/jira-manager

# Create virtual environment and install dependencies
uv venv && uv pip install -e .

# Run scripts with venv Python
.venv/bin/python3 tools/create_ticket.py
.venv/bin/python3 tools/update_ticket.py
```

**Option 3: Using pip (standard method)**:

```bash
cd /path/to/jira-manager

# Install dependencies with pip
pip install -e .

# Run scripts
python tools/create_ticket.py
```

**Option 4: For externally-managed Python (macOS/Homebrew)**:

If you get `externally-managed-environment` error:

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Run scripts
python tools/create_ticket.py
```

**Required packages**:
- `jira` (>=3.10.0) - Jira Server/Data Center API client
- `tomli-w` (>=1.0.0) - TOML file writing
- `tomli` (>=2.0.0) - TOML file reading (only for Python <3.11)

**Verification**:
```bash
python -c "import jira; print('jira:', jira.__version__)"
python -c "import tomli_w; print('tomli_w: installed')"
```

**Note**: Text generation mode (without API integration) requires no dependencies. Dependencies are only needed if you want to create/update tickets directly in Jira via API.

## Template Usage

**Always read** `reference/ticket_templates.md` to ensure:
- Correct summary format
- Proper description structure
- All sections included

Use Jira Wiki Markup for formating:
- Format headings with `h3.`, `h4.`
- Use `*` for bold, `_` for italic
- Format lists with `*` or `#`
- Use `{code:python}` for code blocks
- Format tables with `||heading||` and `|cell|`

Templates are available in English, but the user may ask you to use other languages, in that case do your best to translate.

## Best practices

### When to Use Each Type

**Epic**: 
- Major feature area (e.g., ICP Builder, Brand Style Guide Creator)
- Spans multiple user stories
- Represents significant business value
- Takes 1+ weeks to complete

**Story**: 
- User-facing feature or capability
- Can be completed in 1-3 days
- Has clear acceptance criteria
- Links to parent Epic

**Task**: 
- Technical work without direct user value
- Setup, configuration, refactoring
- Can be completed in hours to 1 day
- May or may not link to Story/Epic

**Bug**: 
- Something is broken or not working as intended
- Has reproduction steps
- Needs fixing urgently based on severity

### Linking Best Practices
- Stories should link to Epics: `additional_fields: {"parent": {"key": "KEY-N"}}`
- Tasks can link to Stories if relevant
- Use issue keys (KEY-N) in commit messages
- Reference related issues in comments

### Writing Quality Standards
- **Be Specific**: "Users can upload PDF, DOCX, or TXT files" vs "Users can upload files"
- **Be Testable**: "Progress bar shows percentage from 0-100%" vs "Progress bar works"
- **Be Complete**: Include edge cases, error states, loading states
- **Be Technical**: Provide enough context for developers and coding agents without being prescriptive

## API Integration Usage

### Creating Tickets via Jira API

When user wants to create ticket directly in Jira Server (not just generate content):

1. **Prepare ticket data** in JSON format with required fields
2. **Call create_ticket.py** via Python:
   ```python
   import json
   import subprocess

   ticket_data = {
       "type": "bug",  # or "task", "story", "epic"
       "summary": "Component - Brief description",
       "description": "Full description in Jira Wiki Markup",
       "priority": "High",  # optional
       "additional_fields": {}  # optional custom fields
   }

   result = subprocess.run(
       ["python", "tools/create_ticket.py"],
       input=json.dumps(ticket_data),
       text=True,
       capture_output=True,
       cwd="/path/to/jira-manager"
   )
   ```

3. **Handle setup wizard** if running for first time:
   - Script will automatically detect missing configuration
   - Wizard prompts will appear in output
   - User provides Jira credentials interactively
   - Configuration saved for future use

4. **Parse response**:
   - Success: Output contains "Success:", issue key, and URL
   - Failure: Output contains "Failed:" and error message

### Configuration Management

**Check existing configuration**:
```python
from tools.config_manager import ConfigManager
config_manager = ConfigManager()
profile = config_manager.get_profile_for_directory("/path/to/project")
```

**Manually add profile** (alternative to wizard):
```python
config_manager.add_profile(
    profile_name="my_project",
    server_url="https://jira.example.com",
    pat="your_pat_token",
    project_key="PROJ",
    directory="/path/to/project"
)
```

### Example Ticket Types

**Bug**:
```json
{
  "type": "bug",
  "summary": "Login page - Users cannot log in with valid credentials",
  "description": "h3. Bug Description\n\nUsers are unable to log in...",
  "priority": "Critical"
}
```

**Story**:
```json
{
  "type": "story",
  "summary": "Step-by-step questionnaire navigation",
  "description": "h3. User Story\n\nAs a user, I want...",
  "additional_fields": {
    "epic_key": "PROJ-123"
  }
}
```

**Epic**:
```json
{
  "type": "epic",
  "summary": "ICP Builder - Ideal Customer Profile Creation",
  "description": "h3. Epic Goal\n\nCreate a comprehensive ICP builder..."
}
```

## Search and Update Operations

### Searching for Issues

When user wants to find existing issues:

1. **Use update_ticket.py with --search**:
   ```python
   import subprocess

   result = subprocess.run(
       ["python", "tools/update_ticket.py", "--search", "text ~ 'login' AND status = Open"],
       capture_output=True,
       text=True,
       cwd="/path/to/jira-manager"
   )
   print(result.stdout)
   ```

2. **Common JQL search patterns**:
   - Find by text: `text ~ 'keyword'`
   - Find by status: `status = Open` or `status IN (Open, "In Progress")`
   - Find by type: `type = Bug`
   - Find by priority: `priority = High`
   - Combine: `text ~ 'login' AND type = Bug AND status = Open`
   - Current user's issues: `assignee = currentUser()`
   - Recently updated: `updated >= -7d` (last 7 days)

3. **Parse search results**:
   - Output contains issue key, summary, type, status, priority, URL
   - Each result on separate line for easy parsing

### Getting Issue Details

When user wants to view full details of a specific issue:

```python
result = subprocess.run(
    ["python", "tools/update_ticket.py", "--get", "PROJ-123"],
    capture_output=True,
    text=True,
    cwd="/path/to/jira-manager"
)
```

Returns:
- Full issue details (key, summary, description, status, type, priority)
- Metadata (created, updated, reporter)
- Parent/epic link if exists
- URL to issue

### Updating Issue Fields

When user wants to modify existing issue:

```python
import json
import subprocess

# Update priority
update_data = {"priority": {"name": "Critical"}}

result = subprocess.run(
    ["python", "tools/update_ticket.py", "--issue", "PROJ-123", "--update", json.dumps(update_data)],
    capture_output=True,
    text=True,
    cwd="/path/to/jira-manager"
)
```

**Common update operations**:
- Change priority: `{"priority": {"name": "High"}}`
- Update summary: `{"summary": "New summary text"}`
- Update description: `{"description": "New description in Jira Wiki Markup"}`
- Multiple fields: `{"priority": {"name": "Critical"}, "summary": "Updated"}`

### Adding Comments

When user wants to add a comment to issue:

```python
result = subprocess.run(
    ["python", "tools/update_ticket.py", "--issue", "PROJ-123", "--comment", "Fixed in PR #456"],
    capture_output=True,
    text=True,
    cwd="/path/to/jira-manager"
)
```

Comments support Jira Wiki Markup formatting.

### Changing Issue Status

When user wants to transition issue to different status:

```python
result = subprocess.run(
    ["python", "tools/update_ticket.py", "--issue", "PROJ-123", "--transition", "In Progress"],
    capture_output=True,
    text=True,
    cwd="/path/to/jira-manager"
)
```

**Common transitions**:
- "To Do" → "In Progress"
- "In Progress" → "Done"
- "Open" → "In Progress" → "Resolved"

Script automatically finds matching transition (case-insensitive) and shows available transitions if specified one not found.

### Workflow Examples

**Find and update bug**:
1. Search: `--search "text ~ 'login' AND type = Bug AND status = Open"`
2. Get details: `--get PROJ-123`
3. Update priority: `--issue PROJ-123 --update '{"priority": {"name": "Critical"}}'`
4. Add comment: `--issue PROJ-123 --comment "Investigating the issue"`
5. Change status: `--issue PROJ-123 --transition "In Progress"`

**Find user's open tasks**:
```python
# Search for current user's open tasks
subprocess.run([
    "python", "tools/update_ticket.py",
    "--search", "assignee = currentUser() AND type = Task AND status != Done"
])
```

**Update multiple issues**:
```python
# Search first
issues = search_and_parse_results(jql_query)

# Update each
for issue_key in issues:
    subprocess.run([
        "python", "tools/update_ticket.py",
        "--issue", issue_key,
        "--update", '{"priority": {"name": "High"}}'
    ])
```

