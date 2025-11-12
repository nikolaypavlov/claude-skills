#!/usr/bin/env python3
import json
import sys
import os
from pathlib import Path
from config_manager import ConfigManager
from jira_client import JiraManager
from setup_wizard import run_setup_wizard


def create_ticket_from_json(ticket_data: dict, directory: str) -> bool:
    """Create a Jira ticket from JSON data

    Args:
        ticket_data: Dict with ticket information
        directory: Current working directory

    Returns:
        True if ticket was created successfully
    """
    # Load configuration
    config_manager = ConfigManager()
    profile = config_manager.get_profile_for_directory(directory)

    # Check if configuration exists
    if not profile:
        print(f"No Jira configuration found for directory: {directory}")
        print()

        # Check if stdin is a TTY (interactive) or pipe/redirect (non-interactive)
        if sys.stdin.isatty():
            # Interactive mode - can run setup wizard
            print("Running setup wizard...")
            print()

            if not run_setup_wizard(directory):
                print("Setup failed. Cannot create ticket.")
                return False

            # Reload profile after setup
            profile = config_manager.get_profile_for_directory(directory)
            if not profile:
                print("Error: Configuration was not saved properly")
                return False
        else:
            # Non-interactive mode (stdin used for data) - cannot run wizard
            print("ERROR: Jira configuration not found.")
            print()
            print("Please run the setup wizard first in a separate command:")
            print()
            print("  # Using uv:")
            print(f"  uv run tools/setup_wizard.py {directory}")
            print()
            print("  # Or with venv Python:")
            print(f"  .venv/bin/python3 tools/setup_wizard.py {directory}")
            print()
            print("  # Or with regular Python:")
            print(f"  python3 tools/setup_wizard.py {directory}")
            print()
            print("After setup is complete, run this command again.")
            return False

    # Extract profile data
    server_url = profile.get("server_url")
    pat = profile.get("pat")
    project_key = profile.get("project_key")

    if not all([server_url, pat, project_key]):
        print("Error: Invalid profile configuration")
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
    # Get current directory
    directory = Path.cwd().resolve().as_posix()

    # Read JSON from stdin or file
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
    success = create_ticket_from_json(ticket_data, directory)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
