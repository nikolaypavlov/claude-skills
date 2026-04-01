# Jira Server Setup Guide

This guide explains how to set up Personal Access Token (PAT) authentication for Jira Server v9.12+ to enable API integration with Jira Manager.

## Prerequisites

- Jira Server version 9.12 or higher
- User account with permission to create issues in your project
- Admin access to enable PAT feature (if not already enabled)

## Step 1: Enable Personal Access Tokens (Admin)

If your Jira Server doesn't have PAT enabled, an administrator must enable it:

1. Log in as Jira Administrator
2. Navigate to **Administration** → **System**
3. Go to **Security** → **Personal Access Tokens**
4. Enable the option "Allow users to create Personal Access Tokens"
5. (Optional) Configure token expiration policy

## Step 2: Create Personal Access Token

### Via Web Interface

1. Log in to your Jira Server instance
2. Click on your **Profile icon** (top right corner)
3. Select **Profile** from the dropdown menu
4. In the left sidebar, click **Personal Access Tokens**
5. Click **Create token** button
6. Fill in the token details:
   - **Token name**: Enter a descriptive name (e.g., "Claude Code Integration")
   - **Expiration**: Choose expiration period or leave blank for no expiration
     - Recommended: 90 days for security
     - For development/testing: Can use longer periods
7. Click **Create**
8. **IMPORTANT**: Copy the generated token immediately
   - This is the only time you'll see the token
   - Store it securely (password manager recommended)
   - You cannot retrieve it later

### Token Format

The token will look like:
```
MzYxNjc5ODE2NTEyOmFGZkVXZzN5R1hTZFVWd3RZbVpQN...
```

## Step 3: Configure Environment Variables

Add your Jira Server URL and PAT to your shell profile:

1. Open your shell profile:
   ```bash
   # For bash
   nano ~/.bash_profile

   # For zsh (macOS default)
   nano ~/.zshenv
   ```

2. Add these lines (replace with your values):
   ```bash
   export JIRA_SERVER_URL="https://jira.example.com"
   export JIRA_API_KEY="your_token_from_step_2"
   ```

3. Save and reload:
   ```bash
   # For bash
   source ~/.bash_profile

   # For zsh
   source ~/.zshenv
   ```

4. Verify:
   ```bash
   echo $JIRA_SERVER_URL
   echo $JIRA_API_KEY
   ```

## Step 4: Verify Setup

Create a test ticket to verify API integration:

```bash
export JIRA_SERVER_URL="https://jira.example.com"
export JIRA_API_KEY="your_token"

echo '{
  "type": "task",
  "project_key": "PROJ",
  "summary": "Test ticket from Jira Manager",
  "description": "This is a test ticket to verify API integration"
}' | uv run tools/create_ticket.py
```

If successful, you'll see:
```
Success: Created Task PROJ-123: https://jira.example.com/browse/PROJ-123
Issue Key: PROJ-123
URL: https://jira.example.com/browse/PROJ-123
```

## Project Key

The project key is passed in each ticket request based on conversation context. To find your project key:

1. Navigate to your project in Jira
2. Look at the URL:
   ```
   https://jira.example.com/projects/PROJ/board/123
   ```
3. The project key is after `/projects/` (e.g., `PROJ`)

Or:
1. Go to **Projects** → **View all projects**
2. The "Key" column shows project keys

## Permissions Required

Your user account needs the following Jira permissions:

- **Browse Projects**: View project and issues
- **Create Issues**: Create new issues
- **Add Comments**: Add comments to issues (optional)
- **Manage Attachments**: Attach files to issues (optional)

To check permissions:
1. Go to your project
2. Click **Project settings** → **Permissions**
3. Find your user or role in the permission scheme
4. Verify you have required permissions

## Advanced Configuration

### Multiple Jira Servers

If you work with multiple Jira servers, you can:

1. **Use shell aliases** for different environments:
   ```bash
   # Add to ~/.bash_profile or ~/.zshenv
   alias jira-work='export JIRA_SERVER_URL="https://jira.work.com" JIRA_API_KEY="work_token"'
   alias jira-personal='export JIRA_SERVER_URL="https://jira.personal.com" JIRA_API_KEY="personal_token"'
   ```
