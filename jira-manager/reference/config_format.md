# Configuration Format Reference

This document describes the structure and format of the Jira Manager configuration file.

## Configuration File Location

**Path**: `~/.config/jira/config.toml`

**Format**: TOML (Tom's Obvious, Minimal Language)

## File Structure

The configuration file has two main sections:

1. **`directory_mappings`**: Maps project directories to profile names
2. **`profiles`**: Defines Jira server configurations

## Complete Example

```toml
[directory_mappings]
"/Users/name/projects/web-app" = "company_main"
"/Users/name/projects/mobile-app" = "company_main"
"/Users/name/projects/client-work" = "client_acme"

[profiles.company_main]
server_url = "https://jira.company.com"
pat = "MzYxNjc5ODE2NTEyOmFGZkVXZzN5..."
project_key = "WEBAPP"

[profiles.client_acme]
server_url = "https://acme.atlassian.net"
pat = "NzEyNDU2Nzg5MDEyOmJHZ1JYZDR6..."
project_key = "ACME"
```

## Directory Mappings Section

### Format

```toml
[directory_mappings]
"<absolute_directory_path>" = "<profile_name>"
```

### Fields

- **Key** (left side): Absolute path to project directory
  - Must be full path (not relative)
  - Case-sensitive on Unix/Linux/macOS
  - Use forward slashes even on Windows

- **Value** (right side): Name of the profile to use
  - Must match a profile name defined in `[profiles.<name>]`
  - Can be any string (alphanumeric, underscores, hyphens)

### Examples

```toml
[directory_mappings]
# Multiple directories can use the same profile
"/Users/john/work/frontend" = "work_jira"
"/Users/john/work/backend" = "work_jira"

# Each directory can have its own profile
"/Users/john/personal/blog" = "personal_jira"
"/Users/john/freelance/client1" = "client1_jira"
```

### How It Works

When you run `create_ticket.py` from `/Users/john/work/frontend`:
1. Script gets current directory: `/Users/john/work/frontend`
2. Looks up directory in `directory_mappings`
3. Finds profile name: `"work_jira"`
4. Loads configuration from `[profiles.work_jira]`

## Profiles Section

### Format

```toml
[profiles.<profile_name>]
server_url = "<jira_server_url>"
pat = "<personal_access_token>"
project_key = "<default_project_key>"
```

### Fields

#### `server_url` (required)

The base URL of your Jira Server instance.

**Format**:
- Must include protocol (`https://` or `http://`)
- Should NOT include trailing slash
- Should NOT include `/rest/api/` or other paths

**Examples**:
```toml
server_url = "https://jira.example.com"              # ✓ Correct
server_url = "https://jira.company.com:8080"         # ✓ Correct (custom port)
server_url = "jira.example.com"                      # ✗ Missing protocol
server_url = "https://jira.example.com/"             # ✗ Trailing slash (works but not recommended)
server_url = "https://jira.example.com/rest/api/"    # ✗ Don't include API path
```

#### `pat` (required)

Personal Access Token for authentication.

**Format**:
- String of base64-encoded characters
- Generated from Jira Server (see `jira_server_setup.md`)
- Should be kept secret

**Examples**:
```toml
pat = "MzYxNjc5ODE2NTEyOmFGZkVXZzN5R1hTZFVWd3RZbVpQN3JxcQ=="    # ✓ Correct
pat = 'MzYxNjc5ODE2NTEyOmFGZkVXZzN5R1hTZFVWd3RZbVpQN3JxcQ=='    # ✓ Also correct (single quotes)
```

**Security Notes**:
- Never commit this file to version control
- Add `~/.config/jira/config.toml` to `.gitignore`
- Use file permissions to restrict access:
  ```bash
  chmod 600 ~/.config/jira/config.toml
  ```

#### `project_key` (required)

The default Jira project key for creating issues.

**Format**:
- Usually 2-10 uppercase letters
- May contain numbers
- No spaces or special characters

**Examples**:
```toml
project_key = "PROJ"          # ✓ Correct
project_key = "WEBAPP"        # ✓ Correct
project_key = "TEAM1"         # ✓ Correct
project_key = "proj"          # ✗ Should be uppercase
project_key = "MY-PROJ"       # ✗ No hyphens allowed
```

**Note**: While this is the default project key, you can override it when creating issues programmatically.

## Multiple Profiles Example

### Scenario: Work + Personal + Client Projects

```toml
[directory_mappings]
# Work projects
"/Users/name/work/api-service" = "company_backend"
"/Users/name/work/web-app" = "company_frontend"

# Personal projects
"/Users/name/personal/blog" = "personal"
"/Users/name/personal/tools" = "personal"

# Client projects
"/Users/name/clients/acme/project" = "acme"
"/Users/name/clients/globex/app" = "globex"

[profiles.company_backend]
server_url = "https://jira.company.com"
pat = "work_backend_token_here"
project_key = "BACKEND"

[profiles.company_frontend]
server_url = "https://jira.company.com"
pat = "work_frontend_token_here"
project_key = "FRONTEND"

[profiles.personal]
server_url = "https://jira.mysite.com"
pat = "personal_token_here"
project_key = "PERS"

[profiles.acme]
server_url = "https://acme-corp.atlassian.net"
pat = "acme_token_here"
project_key = "ACME"

[profiles.globex]
server_url = "https://jira.globex.com"
pat = "globex_token_here"
project_key = "GLOB"
```

## Validation Rules

### Directory Paths

- ✓ Must be absolute paths
- ✓ Must use forward slashes (even on Windows)
- ✓ Can contain spaces (use quotes)
- ✗ Cannot be relative paths (`./project`, `../other`)
- ✗ Cannot use `~` for home directory (use full path)

### Profile Names

- ✓ Can contain letters, numbers, underscores, hyphens
- ✓ Case-sensitive
- ✗ Cannot contain spaces
- ✗ Cannot start with number

### Server URLs

- ✓ Must start with `http://` or `https://`
- ✓ Can include port number
- ✗ Should not end with `/`
- ✗ Should not include path segments

## Programmatic Access

### Reading Configuration

```python
from config_manager import ConfigManager

config = ConfigManager()

# Load entire config
all_config = config.load_config()
print(all_config)

# Get profile for specific directory
profile = config.get_profile_for_directory("/Users/name/project")
print(profile)
# Output: {'server_url': '...', 'pat': '...', 'project_key': '...'}

# List all profiles
profiles = config.list_profiles()
for name, data in profiles.items():
    print(f"{name}: {data['server_url']} ({data['project_key']})")
```

### Adding/Updating Profiles

```python
from config_manager import ConfigManager

config = ConfigManager()

# Add new profile
config.add_profile(
    profile_name="new_project",
    server_url="https://jira.example.com",
    pat="your_token_here",
    project_key="PROJ",
    directory="/path/to/project"
)

# This automatically:
# 1. Creates [profiles.new_project] section
# 2. Adds directory mapping
# 3. Saves to ~/.config/jira/config.toml
```

### Finding Directories for Profile

```python
from config_manager import ConfigManager

config = ConfigManager()

# Get all directories using a profile
directories = config.get_directories_for_profile("company_main")
print(directories)
# Output: ['/Users/name/work/frontend', '/Users/name/work/backend']
```

## Configuration Errors

### Common Issues

**Error**: `No Jira configuration found for directory`

**Cause**: Directory not in `directory_mappings`

**Solution**: Run setup wizard or manually add mapping

---

**Error**: `Invalid profile configuration`

**Cause**: Profile missing required fields

**Solution**: Ensure profile has `server_url`, `pat`, and `project_key`

---

**Error**: `Failed to connect to Jira Server`

**Cause**: Invalid `server_url` or `pat`

**Solution**:
- Verify URL is correct and accessible
- Check PAT is valid and not expired
- Ensure network connectivity

## Best Practices

1. **Organize by workspace/client**
   ```toml
   [profiles.work_team1]
   [profiles.work_team2]
   [profiles.client_acme]
   [profiles.personal]
   ```

2. **Use descriptive profile names**
   ```toml
   # Good
   "company_backend_team"
   "client_acme_project_alpha"

   # Avoid
   "profile1"
   "temp"
   ```

3. **Keep profiles minimal**
   - Don't create duplicate profiles
   - Reuse profiles across similar projects

4. **Secure your config file**
   ```bash
   # Set restrictive permissions
   chmod 600 ~/.config/jira/config.toml

   # Add to .gitignore
   echo "~/.config/jira/config.toml" >> ~/.gitignore
   ```

5. **Document special profiles**
   ```toml
   # Client projects - tokens expire quarterly
   [profiles.client_acme]
   server_url = "https://acme.atlassian.net"
   pat = "token_here"  # Expires: 2024-12-31
   project_key = "ACME"
   ```

## Migration from Other Formats

### From .env Files

**Old format**:
```bash
JIRA_URL=https://jira.example.com
JIRA_PAT=your_token
JIRA_PROJECT=PROJ
```

**New format**:
```toml
[directory_mappings]
"/current/directory" = "main"

[profiles.main]
server_url = "https://jira.example.com"
pat = "your_token"
project_key = "PROJ"
```

### From JSON Config

**Old format**:
```json
{
  "jira": {
    "url": "https://jira.example.com",
    "token": "your_token",
    "project": "PROJ"
  }
}
```

**New format**: Same as above TOML example.

## Schema Version

Current schema version: **1.0**

Future versions may add optional fields but will maintain backward compatibility with existing configurations.
