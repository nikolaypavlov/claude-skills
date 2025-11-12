#!/usr/bin/env python3
import json
import sys
import os
from pathlib import Path
from jira_client import JiraManager


def create_ticket_from_json(ticket_data: dict, server_url: str, pat: str) -> bool:
    """Create a Jira ticket from JSON data

    Args:
        ticket_data: Dict with ticket information (must include 'project_key')
        server_url: Jira Server URL
        pat: Personal Access Token

    Returns:
        True if ticket was created successfully
    """
    # Extract project key from ticket data
    project_key = ticket_data.get("project_key")

    if not project_key:
        print("Error: 'project_key' is required in ticket data")
        print("Example: {\"type\": \"task\", \"project_key\": \"ML\", \"summary\": \"...\", ...}")
        return False

    # Initialize Jira client
    try:
        jira_manager = JiraManager(server_url, pat, project_key)
    except Exception as e:
        print(f"Error initializing Jira client: {str(e)}")
        return False

    # Extract ticket data
    ticket_type = ticket_data.get("type", "").lower()
    summary = ticket_data.get("summary", "")
    description = ticket_data.get("description", "")
    priority = ticket_data.get("priority")
    additional_fields = ticket_data.get("additional_fields", {})

    if not summary or not description:
        print("Error: Summary and description are required")
        return False

    # Create ticket based on type
    print(f"Creating {ticket_type} in Jira...")

    if ticket_type == "bug":
        success, message, issue_key = jira_manager.create_bug(
            summary, description, priority, **additional_fields
        )
    elif ticket_type == "task":
        success, message, issue_key = jira_manager.create_task(
            summary, description, priority, **additional_fields
        )
    elif ticket_type == "story":
        epic_key = additional_fields.pop("epic_key", None)
        success, message, issue_key = jira_manager.create_story(
            summary, description, priority, epic_key, **additional_fields
        )
    elif ticket_type == "epic":
        epic_name = additional_fields.pop("epic_name", None)
        success, message, issue_key = jira_manager.create_epic(
            summary, description, epic_name, **additional_fields
        )
    else:
        print(f"Error: Unknown ticket type '{ticket_type}'")
        print("Supported types: bug, task, story, epic")
        return False

    # Output result
    if success:
        print(f"Success: {message}")
        if issue_key:
            print(f"Issue Key: {issue_key}")
            print(f"URL: {server_url}/browse/{issue_key}")
        return True
    else:
        print(f"Failed: {message}")
        return False


def main():
    """Main entry point for create_ticket CLI"""
    # Check for required environment variables
    server_url = os.environ.get("JIRA_SERVER_URL")
    pat = os.environ.get("JIRA_API_KEY")

    if not server_url or not pat:
        error_msg = """
ENVIRONMENT VARIABLES REQUIRED

Jira Manager requires environment variables to be set:

Missing variables:
"""
        if not server_url:
            error_msg += "  - JIRA_SERVER_URL (e.g., https://jira.example.com)\n"
        if not pat:
            error_msg += "  - JIRA_API_KEY (Personal Access Token for authentication)\n"

        error_msg += """
ACTION FOR CLAUDE CODE:
Set these environment variables before running this tool.

Example:
  export JIRA_SERVER_URL="https://jira.example.com"
  export JIRA_API_KEY="your-personal-access-token"

WHY:
- JIRA_SERVER_URL: URL of your Jira Server instance
- JIRA_API_KEY: Personal Access Token for authentication (Jira Server 9.12+)

The project_key should be included in the ticket JSON data based on user context.
"""
        print(error_msg)
        sys.exit(1)

    # THEN: Read JSON from stdin or file
    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            print("Error: --file option requires a filename")
            sys.exit(1)

        try:
            with open(sys.argv[2], 'r') as f:
                ticket_data = json.load(f)
        except FileNotFoundError:
            print(f"Error: File not found: {sys.argv[2]}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in file: {str(e)}")
            sys.exit(1)
    else:
        # Read from stdin
        try:
            ticket_data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON input: {str(e)}")
            print()
            print("Usage:")
            print("  echo '{\"type\": \"bug\", ...}' | python create_ticket.py")
            print("  python create_ticket.py --file ticket.json")
            sys.exit(1)

    # Create ticket
    success = create_ticket_from_json(ticket_data, server_url, pat)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
