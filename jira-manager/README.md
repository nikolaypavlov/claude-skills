# Jira Manager

Claude Code skill for generating structured Jira tickets and integrating with Jira Server API. Supports templates for bugs, tasks, stories, and epics with simple environment variable configuration.

## Features

- **Template-Based Ticket Generation**: Structured templates for Bug, Task, Story, and Epic
- **Jira Wiki Markup**: Properly formatted content ready to copy-paste
- **Jira Server API Integration**: Direct ticket creation via Personal Access Tokens (PAT)
- **Simple Configuration**: Two environment variables, no config files
- **Context-Aware**: Project key extracted from conversation context
- **Multi-Language Support**: Generate tickets in any language

## Requirements

- Python >= 3.10
- Jira Server v9.12+ (for API integration)
- Personal Access Token (for API integration)

## Installation

Install via Claude Code marketplace:

```bash
/plugin install jira-manager
```

For API integration, install Python dependencies:

```bash
cd jira-manager
uv pip install -e .
```

## Quick Start

### Text Generation Mode

Ask Claude to create a Jira ticket:

```
Create a bug ticket for login issue where users can't authenticate
```

Claude will:
1. Ask for details (reproduction steps, environment, etc.)
2. Generate formatted Jira Wiki Markup content
3. Provide ready-to-paste content for Jira

### API Integration Mode

Ask Claude to create a ticket directly in Jira:

```
Create this bug ticket directly in the PROJ project
```

Claude will:
- Use environment variables for authentication
- Extract project key (PROJ) from your message
- Create ticket via Jira API
- Return issue key and URL

## Configuration

### Environment Variables

Add these to your shell profile (`~/.bash_profile` or `~/.zshenv`):

```bash
export JIRA_SERVER_URL="https://jira.example.com"
export JIRA_API_KEY="your_personal_access_token"
```

Then reload your shell or run:
```bash
source ~/.bash_profile  # or ~/.zshenv
```

### Creating Personal Access Token

1. Log in to your Jira Server
2. Go to Profile → Personal Access Tokens
3. Click "Create token"
4. Name it (e.g., "Claude Code Integration")
5. Set expiration (optional)
6. Copy the generated token

See `reference/jira_server_setup.md` for detailed instructions.

### Project Key

The project key is extracted from your conversation with Claude:
- "Create ticket in PROJ project" → project_key: PROJ
- "Add bug to WORK project" → project_key: WORK

No configuration file needed!

## Usage Examples

### Bug Ticket

```
Create a bug: Users cannot upload files larger than 5MB.
Environment: Chrome 118, Production.
Steps: 1) Go to upload page 2) Select 10MB file 3) Click upload 4) Error appears
```

### Story Ticket

```
Create a story: As a user, I want to export my data as CSV,
so that I can analyze it in Excel. Link it to epic PROJ-123.
```

### Epic Ticket

```
Create an epic for ICP Builder feature that will help users
create ideal customer profiles through step-by-step questionnaire.
```

### Task Ticket

```
Create a task: Set up GitHub Actions CI/CD pipeline with
automated testing and deployment to staging environment.
```

## Template Structure

All tickets follow consistent templates from `reference/ticket_templates.md`:

- **Bug**: Description, Steps to Reproduce, Expected/Actual Behavior, Environment
- **Task**: Description, Context, Steps, Expected Outcome
- **Story**: User Story, Acceptance Criteria, Technical Notes, Definition of Done
- **Epic**: Epic Goal, Business Value, Scope, Success Criteria, Dependencies

## Search and Update Operations

### Searching for Issues

Find existing issues using JQL (Jira Query Language):

```bash
# Search for open bugs containing "login"
python tools/update_ticket.py --search "text ~ 'login' AND type = Bug AND status = Open"

# Find your assigned open issues
python tools/update_ticket.py --search "assignee = currentUser() AND status != Done"

# Find high-priority bugs updated in last 7 days
python tools/update_ticket.py --search "type = Bug AND priority = High AND updated >= -7d"
```

### Getting Issue Details

View complete information about a specific issue:

```bash
python tools/update_ticket.py --get PROJ-123
```

Returns: summary, description, status, type, priority, created/updated dates, reporter, and URL.

### Updating Issues

Modify existing issues:

```bash
# Update priority
python tools/update_ticket.py --issue PROJ-123 --update '{"priority": {"name": "Critical"}}'

# Update summary
python tools/update_ticket.py --issue PROJ-123 --update '{"summary": "New summary"}'

# Update multiple fields
python tools/update_ticket.py --issue PROJ-123 --update '{"priority": {"name": "High"}, "summary": "Updated summary"}'
```

### Adding Comments

Add comments with Jira Wiki Markup support:

```bash
python tools/update_ticket.py --issue PROJ-123 --comment "Fixed in PR #456. Deploying to staging."
```

### Changing Issue Status

Transition issues to different statuses:

```bash
# Move to In Progress
python tools/update_ticket.py --issue PROJ-123 --transition "In Progress"

# Mark as Done
python tools/update_ticket.py --issue PROJ-123 --transition "Done"
```

### Complete Workflow Example

```bash
# 1. Search for open bugs
python tools/update_ticket.py --search "type = Bug AND status = Open" --max-results 10

# 2. Get details of specific bug
python tools/update_ticket.py --get PROJ-123

# 3. Update priority
python tools/update_ticket.py --issue PROJ-123 --update '{"priority": {"name": "Critical"}}'

# 4. Add investigation comment
python tools/update_ticket.py --issue PROJ-123 --comment "Investigating. Root cause found in auth module."

# 5. Move to In Progress
python tools/update_ticket.py --issue PROJ-123 --transition "In Progress"
```

## Troubleshooting

### Missing Environment Variables

```
ENVIRONMENT VARIABLES REQUIRED
Missing variables:
  - JIRA_SERVER_URL
  - JIRA_API_KEY
```

Solutions:
- Add environment variables to `~/.bash_profile` or `~/.zshenv`
- Reload shell: `source ~/.bash_profile`
- Verify with: `echo $JIRA_SERVER_URL`

### Connection Issues

```
Error: Failed to connect to Jira Server
```

Solutions:
- Verify `JIRA_SERVER_URL` is correct (including https://)
- Check `JIRA_API_KEY` (Personal Access Token) is valid and not expired
- Ensure network access to Jira Server
- Verify Jira Server version is 9.12+

### Permission Issues

```
Error: Insufficient permissions to create issues
```

Solutions:
- Verify PAT has Create Issues permission
- Check project key is correct
- Ensure user has access to the project

### Configuration Issues

To reset configuration:

```bash
rm ~/.config/jira/config.toml
```

Next API request will trigger setup wizard again.

## API Integration Details

### Manual Ticket Creation

```python
import json
import subprocess

ticket = {
    "type": "bug",
    "summary": "Login - Cannot authenticate with valid credentials",
    "description": "h3. Bug Description\n\nUsers are unable to log in...",
    "priority": "High"
}

result = subprocess.run(
    ["python", "tools/create_ticket.py"],
    input=json.dumps(ticket),
    text=True,
    capture_output=True,
    cwd="/path/to/jira-manager"
)

print(result.stdout)
```

### Configuration Management

```python
from tools.config_manager import ConfigManager

config = ConfigManager()

# Add new profile
config.add_profile(
    profile_name="my_project",
    server_url="https://jira.example.com",
    pat="your_pat_here",
    project_key="PROJ",
    directory="/path/to/project"
)

# Get profile for directory
profile = config.get_profile_for_directory("/path/to/project")
print(profile)  # {'server_url': '...', 'pat': '...', 'project_key': '...'}
```

## Files and Structure

```
jira-manager/
├── SKILL.md                           # Skill instructions for Claude
├── README.md                          # This file
├── pyproject.toml                     # Python dependencies
├── reference/                         # Reference documentation
│   ├── ticket_templates.md            # Template definitions
│   ├── jira_server_setup.md           # PAT setup guide
│   └── config_format.md               # Configuration reference
├── examples/                          # Example tickets and code
│   ├── bug_example.md
│   ├── story_example.md
│   ├── task_example.md
│   ├── epic_example.md
│   ├── config_example.toml
│   ├── api_usage.py                   # CREATE operations examples
│   └── update_operations_example.py   # SEARCH/UPDATE examples
└── tools/                             # Python API integration
    ├── config_manager.py              # Configuration management
    ├── jira_client.py                 # Jira API client (CRUD operations)
    ├── setup_wizard.py                # Interactive setup
    ├── create_ticket.py               # CLI for creating tickets
    └── update_ticket.py               # CLI for search/update/comment
```

## License

MIT

## Author

Mykola Pavlov (me@nikolaypavlov.com)
