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

## Step 3: Find Your Project Key

You need the project key to configure Jira Manager:

1. Navigate to your project in Jira
2. Look at the URL, it will be something like:
   ```
   https://jira.example.com/projects/PROJ/board/123
   ```
3. The project key is the part after `/projects/` (e.g., `PROJ`)

Alternatively:
1. Go to **Projects** → **View all projects**
2. Find your project in the list
3. The project key is shown in the "Key" column

## Step 4: Configure Jira Manager

### Automatic Setup (Recommended)

When you first try to create a ticket via API, Jira Manager will automatically run the setup wizard:

1. You'll be prompted for:
   - Jira Server URL (e.g., `https://jira.example.com`)
   - Personal Access Token (paste the token from Step 2)
   - Project Key (from Step 3)

2. The wizard will test the connection

3. Configuration will be saved to `~/.config/jira/config.toml`

### Manual Setup

You can manually create the configuration file:

1. Create directory: `~/.config/jira/`
2. Create file: `~/.config/jira/config.toml`
3. Add your configuration:

```toml
[directory_mappings]
"/path/to/your/project" = "your_profile_name"

[profiles.your_profile_name]
server_url = "https://jira.example.com"
pat = "your_token_here"
project_key = "PROJ"
```

## Step 5: Verify Setup

Test your configuration:

```python
python tools/setup_wizard.py /path/to/your/project
```

Or create a test ticket to verify:

```python
echo '{
  "type": "task",
  "summary": "Test ticket from Jira Manager",
  "description": "This is a test ticket to verify API integration"
}' | python tools/create_ticket.py
```

If successful, you'll see:
```
Success: Created Task PROJ-123: https://jira.example.com/browse/PROJ-123
```

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

## Security Best Practices

### Token Management

1. **Never commit tokens to version control**
   - Add `~/.config/jira/config.toml` to your `.gitignore`
   - Use environment variables for shared configurations

2. **Rotate tokens regularly**
   - Set expiration dates (recommended: 90 days)
   - Revoke old tokens when creating new ones

3. **Use separate tokens per device/application**
   - Easier to track usage
   - Can revoke specific token without affecting others
   - Name tokens descriptively (e.g., "MacBook-Claude-Code")

4. **Revoke tokens immediately if compromised**
   - Go to Profile → Personal Access Tokens
   - Click **Revoke** next to the compromised token

### Token Storage

- **Do**: Store in password manager or encrypted storage
- **Do**: Use OS keychain/credential manager when possible
- **Don't**: Store in plain text files in the project
- **Don't**: Share tokens via email or chat
- **Don't**: Include in screenshots or documentation

## Troubleshooting

### Connection Failed: Invalid Token

**Problem**: "Authentication failed" or "401 Unauthorized"

**Solutions**:
- Verify token is copied correctly (no extra spaces)
- Check token hasn't expired
- Ensure PAT feature is enabled on Jira Server
- Try creating a new token

### Connection Failed: Cannot Reach Server

**Problem**: "Connection timeout" or "Cannot connect"

**Solutions**:
- Verify server URL is correct (include `https://`)
- Check network connectivity
- Verify VPN is connected (if required)
- Check firewall settings

### Permission Denied

**Problem**: "Insufficient permissions to create issues"

**Solutions**:
- Verify project key is correct
- Check user has "Create Issues" permission
- Contact Jira administrator to grant permissions
- Try a different project where you have permissions

### Token Expiration Warnings

Jira will send email notifications 5 days before token expiration. To renew:

1. Create a new token following Step 2
2. Update `~/.config/jira/config.toml` with new token
3. Revoke the old token

## Advanced Configuration

### Multiple Jira Servers

You can configure different Jira servers for different projects:

```toml
[directory_mappings]
"/path/to/work-project" = "work_jira"
"/path/to/personal-project" = "personal_jira"

[profiles.work_jira]
server_url = "https://jira.company.com"
pat = "work_token"
project_key = "WORK"

[profiles.personal_jira]
server_url = "https://jira.mysite.com"
pat = "personal_token"
project_key = "PERS"
```

### Token Expiration Configuration

Administrators can configure default expiration in Jira:

1. Navigate to Administration → System
2. Go to Advanced settings
3. Set property:
   ```
   -Datlassian.pats.max.tokens.expiry.days=365
   ```
4. Restart Jira for changes to take effect

## Support and Resources

- [Atlassian PAT Documentation](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html)
- [Jira Server REST API Documentation](https://docs.atlassian.com/software/jira/docs/api/REST/)
- Jira Manager GitHub Issues: Report problems or ask questions

## Frequently Asked Questions

**Q: Can I use the same token for multiple directories?**
A: Yes, you can reuse the same PAT across multiple profiles. However, using separate tokens per project/device is recommended for better security and tracking.

**Q: What happens if my token expires?**
A: You'll receive error messages when trying to create tickets. Create a new token and update your configuration.

**Q: Can I use API tokens from Jira Cloud?**
A: No, this integration is designed for Jira Server/Data Center. Jira Cloud uses different authentication (email + API token instead of PAT).

**Q: How do I revoke a token?**
A: Profile → Personal Access Tokens → Find the token → Click "Revoke"

**Q: Can I see which tokens are being used?**
A: Jira shows last used date for each token in the Personal Access Tokens page.
