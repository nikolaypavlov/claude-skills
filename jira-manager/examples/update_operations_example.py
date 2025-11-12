#!/usr/bin/env python3
"""
Example of searching and updating Jira issues

This script demonstrates how to:
1. Search for issues using JQL
2. Get detailed information about specific issues
3. Update issue fields
4. Add comments
5. Transition issues to different statuses

Prerequisites:
  export JIRA_SERVER_URL="https://jira.example.com"
  export JIRA_API_KEY="your_personal_access_token"
"""

import os
import sys
from pathlib import Path

# Add tools to path
tools_path = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(tools_path))

from jira_client import JiraManager


def check_environment():
    """Check if required environment variables are set"""
    server_url = os.environ.get("JIRA_SERVER_URL")
    api_key = os.environ.get("JIRA_API_KEY")

    if not server_url or not api_key:
        print("ERROR: Required environment variables not set")
        print("\nPlease set:")
        if not server_url:
            print("  export JIRA_SERVER_URL='https://jira.example.com'")
        if not api_key:
            print("  export JIRA_API_KEY='your_personal_access_token'")
        sys.exit(1)

    return server_url, api_key


def example_search_issues(jira: JiraManager):
    """Example: Search for issues using JQL"""
    print("=== Searching for Issues ===\n")

    # Search for open bugs containing "login" in text
    jql_query = "text ~ 'login' AND type = Bug AND status = Open"
    success, message, issues = jira.search_issues(jql_query, max_results=10)

    if success and issues:
        print(f"{message}")
        print("-" * 80)
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue['key']}: {issue['summary']}")
            print(f"   Type: {issue['issue_type']} | Status: {issue['status']} | Priority: {issue['priority']}")
            print(f"   URL: {issue['url']}")
            print()
    elif success:
        print("No issues found")
    else:
        print(f"Search failed: {message}")
    print()


def example_search_user_issues(jira: JiraManager):
    """Example: Search for current user's issues"""
    print("=== Searching Current User's Open Issues ===\n")

    # Find all open issues assigned to current user
    jql_query = "assignee = currentUser() AND status != Done"
    success, message, issues = jira.search_issues(jql_query)

    if success and issues:
        print(f"Found {len(issues)} open issues:")
        for issue in issues:
            print(f"- {issue['key']}: {issue['summary']} ({issue['status']})")
    elif success:
        print("No open issues found")
    else:
        print(f"Search failed: {message}")
    print()


def example_get_issue_details(jira: JiraManager, issue_key: str):
    """Example: Get detailed information about an issue"""
    print(f"=== Getting Details for {issue_key} ===\n")

    success, message, issue_data = jira.get_issue(issue_key)

    if success and issue_data:
        print("Issue Details:")
        print(f"  Key: {issue_data['key']}")
        print(f"  Summary: {issue_data['summary']}")
        print(f"  Type: {issue_data['issue_type']}")
        print(f"  Status: {issue_data['status']}")
        print(f"  Priority: {issue_data['priority']}")
        print(f"  Reporter: {issue_data['reporter']}")
        print(f"  Created: {issue_data['created']}")
        print(f"  Updated: {issue_data['updated']}")
        if issue_data.get('parent'):
            print(f"  Parent: {issue_data['parent']}")
        print()
        print("Description:")
        print(f"  {issue_data['description'][:200]}..." if len(issue_data['description']) > 200 else f"  {issue_data['description']}")
        print()
        print(f"  URL: {issue_data['url']}")
    else:
        print(f"Failed: {message}")
    print()


def example_update_priority(jira: JiraManager, issue_key: str):
    """Example: Update issue priority"""
    print(f"=== Updating Priority for {issue_key} ===\n")

    # Update priority to High
    success, message = jira.update_issue(
        issue_key,
        {"priority": {"name": "High"}}
    )

    if success:
        print(f"Success: {message}")
    else:
        print(f"Failed: {message}")
    print()


def example_update_summary(jira: JiraManager, issue_key: str):
    """Example: Update issue summary"""
    print(f"=== Updating Summary for {issue_key} ===\n")

    # Update summary
    success, message = jira.update_issue(
        issue_key,
        {"summary": "Login page - Users cannot authenticate (URGENT)"}
    )

    if success:
        print(f"Success: {message}")
    else:
        print(f"Failed: {message}")
    print()


def example_update_multiple_fields(jira: JiraManager, issue_key: str):
    """Example: Update multiple fields at once"""
    print(f"=== Updating Multiple Fields for {issue_key} ===\n")

    # Update priority and description
    success, message = jira.update_issue(
        issue_key,
        {
            "priority": {"name": "Critical"},
            "description": "h3. Bug Description\n\nThis is an updated description with Jira Wiki Markup.\n\n*Priority*: Critical\n*Impact*: All users affected"
        }
    )

    if success:
        print(f"Success: {message}")
    else:
        print(f"Failed: {message}")
    print()


def example_add_comment(jira: JiraManager, issue_key: str):
    """Example: Add a comment to an issue"""
    print(f"=== Adding Comment to {issue_key} ===\n")

    comment_text = """h4. Investigation Update

Investigated the issue and found the root cause:
* Authentication token validation is failing
* Issue is in {{auth.service.ts:45}}

h4. Next Steps
# Fix token validation logic
# Add unit tests
# Deploy to staging for testing

*ETA*: 2 days
"""

    success, message = jira.add_comment(issue_key, comment_text)

    if success:
        print(f"Success: {message}")
    else:
        print(f"Failed: {message}")
    print()


def example_get_available_transitions(jira: JiraManager, issue_key: str):
    """Example: Get available status transitions"""
    print(f"=== Available Transitions for {issue_key} ===\n")

    success, message, transitions = jira.get_issue_transitions(issue_key)

    if success and transitions:
        print(f"Available transitions ({len(transitions)}):")
        for t in transitions:
            print(f"  - {t['name']} (ID: {t['id']})")
    else:
        print(f"Failed: {message}")
    print()


def example_transition_issue(jira: JiraManager, issue_key: str, transition_name: str):
    """Example: Change issue status"""
    print(f"=== Transitioning {issue_key} to '{transition_name}' ===\n")

    success, message = jira.transition_issue(issue_key, transition_name)

    if success:
        print(f"Success: {message}")
    else:
        print(f"Failed: {message}")
    print()


def example_workflow(jira: JiraManager):
    """Example: Complete workflow - search, get, update, comment, transition"""
    print("=== Complete Workflow Example ===\n")

    # Step 1: Search for open high-priority bugs
    print("Step 1: Searching for open high-priority bugs...")
    jql_query = "type = Bug AND priority = High AND status = Open"
    success, message, issues = jira.search_issues(jql_query, max_results=5)

    if not success or not issues:
        print(f"No high-priority bugs found or search failed: {message}")
        return

    # Get first issue
    issue_key = issues[0]['key']
    print(f"Found issue: {issue_key}")
    print()

    # Step 2: Get full details
    print(f"Step 2: Getting details for {issue_key}...")
    success, message, issue_data = jira.get_issue(issue_key)
    if success:
        print(f"  Summary: {issue_data['summary']}")
        print(f"  Status: {issue_data['status']}")
    print()

    # Step 3: Update priority to Critical
    print(f"Step 3: Escalating priority to Critical...")
    success, message = jira.update_issue(issue_key, {"priority": {"name": "Critical"}})
    print(f"  {message}")
    print()

    # Step 4: Add investigation comment
    print(f"Step 4: Adding investigation comment...")
    success, message = jira.add_comment(issue_key, "Escalated to Critical. Investigating now.")
    print(f"  {message}")
    print()

    # Step 5: Transition to In Progress
    print(f"Step 5: Moving to In Progress...")
    success, message = jira.transition_issue(issue_key, "In Progress")
    print(f"  {message}")
    print()

    print("Workflow completed!")
    print("=" * 80)


def main():
    """Main example function"""
    print("Jira Manager - Update Operations Examples")
    print("=" * 80)
    print()

    # Check environment variables
    server_url, api_key = check_environment()

    # Project key - in real usage, this comes from conversation context
    # For this example, specify your project key here
    PROJECT_KEY = "PROJ"  # Change to your project key

    try:
        jira = JiraManager(server_url, api_key, PROJECT_KEY)

        # Test connection
        success, message = jira.test_connection()
        if not success:
            print(f"Connection failed: {message}")
            return

        print(f"Connected: {message}\n")

        # Run search examples
        example_search_issues(jira)
        example_search_user_issues(jira)

        # NOTE: Replace PROJ-123 with an actual issue key from your Jira
        EXAMPLE_ISSUE_KEY = "PROJ-123"

        # Run get/update examples (uncomment to use)
        # example_get_issue_details(jira, EXAMPLE_ISSUE_KEY)
        # example_update_priority(jira, EXAMPLE_ISSUE_KEY)
        # example_update_summary(jira, EXAMPLE_ISSUE_KEY)
        # example_update_multiple_fields(jira, EXAMPLE_ISSUE_KEY)
        # example_add_comment(jira, EXAMPLE_ISSUE_KEY)
        # example_get_available_transitions(jira, EXAMPLE_ISSUE_KEY)
        # example_transition_issue(jira, EXAMPLE_ISSUE_KEY, "In Progress")

        # Run complete workflow (uncomment to use)
        # example_workflow(jira)

        print("=" * 80)
        print("Examples completed!")
        print()
        print("NOTE: Update operations are commented out to avoid accidental changes.")
        print("Uncomment the examples you want to try with a real issue key.")

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
