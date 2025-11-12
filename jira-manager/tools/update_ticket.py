#!/usr/bin/env python3
import json
import sys
import argparse
from pathlib import Path
from config_manager import ConfigManager
from jira_client import JiraManager
from setup_wizard import run_setup_wizard


def search_issues_command(jira: JiraManager, jql_query: str, max_results: int) -> bool:
    """Execute search issues command"""
    print(f"Searching for issues: {jql_query}")
    print()

    success, message, issues = jira.search_issues(jql_query, max_results)

    if success and issues:
        print(f"{message}")
        print("=" * 80)
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue['key']}: {issue['summary']}")
            print(f"   Type: {issue['issue_type']} | Status: {issue['status']} | Priority: {issue['priority']}")
            print(f"   URL: {issue['url']}")
            print()
        return True
    elif success and not issues:
        print("No issues found matching the query")
        return True
    else:
        print(f"Search failed: {message}")
        return False


def get_issue_command(jira: JiraManager, issue_key: str) -> bool:
    """Execute get issue command"""
    print(f"Retrieving issue: {issue_key}")
    print()

    success, message, issue_data = jira.get_issue(issue_key)

    if success and issue_data:
        print("=" * 80)
        print(f"Key: {issue_data['key']}")
        print(f"Summary: {issue_data['summary']}")
        print(f"Type: {issue_data['issue_type']}")
        print(f"Status: {issue_data['status']}")
        print(f"Priority: {issue_data['priority']}")
        print(f"Reporter: {issue_data['reporter']}")
        print(f"Created: {issue_data['created']}")
        print(f"Updated: {issue_data['updated']}")
        if issue_data.get('parent'):
            print(f"Parent: {issue_data['parent']}")
        print()
        print("Description:")
        print("-" * 80)
        print(issue_data['description'])
        print("-" * 80)
        print()
        print(f"URL: {issue_data['url']}")
        print("=" * 80)
        return True
    else:
        print(f"Failed: {message}")
        return False


def update_issue_command(jira: JiraManager, issue_key: str, update_data: dict) -> bool:
    """Execute update issue command"""
    print(f"Updating issue: {issue_key}")
    print(f"Fields to update: {list(update_data.keys())}")
    print()

    success, message = jira.update_issue(issue_key, update_data)

    if success:
        print(f"Success: {message}")
        return True
    else:
        print(f"Failed: {message}")
        return False


def add_comment_command(jira: JiraManager, issue_key: str, comment_text: str) -> bool:
    """Execute add comment command"""
    print(f"Adding comment to: {issue_key}")
    print()

    success, message = jira.add_comment(issue_key, comment_text)

    if success:
        print(f"Success: {message}")
        return True
    else:
        print(f"Failed: {message}")
        return False


def transition_issue_command(jira: JiraManager, issue_key: str, transition_name: str) -> bool:
    """Execute transition issue command"""
    print(f"Transitioning issue: {issue_key} to '{transition_name}'")
    print()

    # First, get available transitions
    success, msg, transitions = jira.get_issue_transitions(issue_key)
    if success and transitions:
        print(f"Available transitions: {', '.join([t['name'] for t in transitions])}")
        print()

    # Execute transition
    success, message = jira.transition_issue(issue_key, transition_name)

    if success:
        print(f"Success: {message}")
        return True
    else:
        print(f"Failed: {message}")
        return False


def main():
    """Main entry point for update_ticket CLI"""
    parser = argparse.ArgumentParser(
        description="Search and update Jira tickets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Search for issues:
    python update_ticket.py --search "text ~ 'login' AND status = Open"
    python update_ticket.py --search "project = PROJ AND assignee = currentUser()"

  Get issue details:
    python update_ticket.py --get PROJ-123

  Update issue fields:
    python update_ticket.py --issue PROJ-123 --update '{"priority": {"name": "High"}}'
    python update_ticket.py --issue PROJ-123 --update '{"summary": "New summary"}'

  Add comment:
    python update_ticket.py --issue PROJ-123 --comment "Fixed in PR #456"

  Transition issue:
    python update_ticket.py --issue PROJ-123 --transition "In Progress"
    python update_ticket.py --issue PROJ-123 --transition "Done"
        """
    )

    # Search operations
    parser.add_argument("--search", type=str, help="JQL query to search for issues")
    parser.add_argument("--max-results", type=int, default=50, help="Maximum search results (default: 50)")

    # Get issue
    parser.add_argument("--get", type=str, help="Get details of specific issue by key")

    # Update operations (require --issue)
    parser.add_argument("--issue", type=str, help="Issue key for update operations")
    parser.add_argument("--update", type=str, help="JSON object with fields to update")
    parser.add_argument("--comment", type=str, help="Comment text to add")
    parser.add_argument("--transition", type=str, help="Transition name (e.g., 'In Progress', 'Done')")

    args = parser.parse_args()

    # Validate arguments
    if not any([args.search, args.get, args.update, args.comment, args.transition]):
        parser.print_help()
        sys.exit(1)

    # Update operations require --issue
    if (args.update or args.comment or args.transition) and not args.issue:
        print("Error: --update, --comment, and --transition require --issue")
        sys.exit(1)

    # Get current directory
    directory = Path.cwd().resolve().as_posix()

    # Load configuration
    config_manager = ConfigManager()
    profile = config_manager.get_profile_for_directory(directory)

    # Check if configuration exists
    if not profile:
        print(f"No Jira configuration found for directory: {directory}")
        print()

        # For update_ticket, stdin is free so wizard can run
        # But add check for consistency and better error handling
        print("Running setup wizard...")
        print()

        try:
            if not run_setup_wizard(directory):
                print("Setup failed. Cannot proceed.")
                sys.exit(1)
        except (EOFError, KeyboardInterrupt):
            print()
            print("Setup interrupted.")
            print()
            print("You can run setup later with:")
            print(f"  python3 tools/setup_wizard.py {directory}")
            sys.exit(1)

        # Reload profile after setup
        profile = config_manager.get_profile_for_directory(directory)
        if not profile:
            print("Error: Configuration was not saved properly")
            sys.exit(1)

    # Extract profile data
    server_url = profile.get("server_url")
    pat = profile.get("pat")
    project_key = profile.get("project_key")

    if not all([server_url, pat, project_key]):
        print("Error: Invalid profile configuration")
        sys.exit(1)

    # Initialize Jira client
    try:
        jira = JiraManager(server_url, pat, project_key)
    except Exception as e:
        print(f"Error initializing Jira client: {str(e)}")
        sys.exit(1)

    # Execute commands
    success = True

    if args.search:
        success = search_issues_command(jira, args.search, args.max_results)

    elif args.get:
        success = get_issue_command(jira, args.get)

    elif args.update:
        try:
            update_data = json.loads(args.update)
            success = update_issue_command(jira, args.issue, update_data)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in --update: {str(e)}")
            success = False

    elif args.comment:
        success = add_comment_command(jira, args.issue, args.comment)

    elif args.transition:
        success = transition_issue_command(jira, args.issue, args.transition)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
