#!/usr/bin/env python3
"""
Example of using Jira Manager API programmatically

This script demonstrates how to:
1. Use environment variables for authentication
2. Create different types of tickets
3. Link issues to epics
4. Retrieve project metadata

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


def example_create_bug(jira: JiraManager):
    """Example: Create a bug ticket"""
    print("=== Creating Bug Ticket ===\n")

    success, message, issue_key = jira.create_bug(
        summary="Login page - Cannot authenticate with valid credentials",
        description="""h3. Bug Description

Users are unable to log in even with valid credentials.

h3. Steps to Reproduce

# Navigate to login page
# Enter valid username and password
# Click "Log In" button
# Observe error message

h3. Expected Behavior

User should be redirected to dashboard

h3. Actual Behavior

Error message appears: "Authentication failed"

h3. Environment

* Browser: Chrome 118
* OS: macOS 14.1
* Environment: Production

h3. Severity

Critical - blocks user access""",
        priority="Critical"
    )

    if success:
        print(f"Success! Created bug: {issue_key}")
        print(f"Message: {message}")
    else:
        print(f"Failed: {message}")
    print()
    return issue_key if success else None


def example_create_epic(jira: JiraManager):
    """Example: Create an epic"""
    print("=== Creating Epic ===\n")

    success, message, epic_key = jira.create_epic(
        summary="ICP Builder - Ideal Customer Profile Creation",
        description="""h3. Epic Goal

Create comprehensive ICP builder with AI-powered suggestions.

h3. Business Value

* Increase conversion rates by 25%
* Reduce time-to-value from 2 weeks to 2 days
* Differentiate from competitors

h3. Scope

* Phase 1: Core questionnaire
* Phase 2: AI enhancements
* Phase 3: Export and integration
* Phase 4: Collaboration features

h3. Success Criteria

* 60% adoption rate within first month
* 80% completion rate
* Average completion time under 15 minutes"""
    )

    if success:
        print(f"Success! Created epic: {epic_key}")
        print(f"Message: {message}")
    else:
        print(f"Failed: {message}")
    print()
    return epic_key if success else None


def example_create_story(jira: JiraManager, epic_key: str = None):
    """Example: Create a story (optionally linked to epic)"""
    print("=== Creating Story ===\n")

    if epic_key:
        print(f"Linking to epic: {epic_key}")

    success, message, issue_key = jira.create_story(
        summary="Step-by-step questionnaire navigation",
        description="""h3. User Story

As a user, I want to navigate through questionnaire with progress tracking.

h3. Acceptance Criteria

h4. 1. Navigation Controls

* Previous/Next buttons on each step
* Previous disabled on first step
* Next disabled on last step
* Keyboard navigation support

h4. 2. Progress Indicator

* Progress bar shows percentage (0-100%)
* Displays "Step X of Y"
* Completed steps marked with checkmark

h3. Technical Notes

* Component: `src/components/Questionnaire/Navigation.tsx`
* State: React Context
* Validation: Zod

h3. Definition of Done

* All criteria met
* Tests written
* Code reviewed
* Documentation updated""",
        priority="High",
        epic_key=epic_key
    )

    if success:
        print(f"Success! Created story: {issue_key}")
        print(f"Message: {message}")
    else:
        print(f"Failed: {message}")
    print()
    return issue_key if success else None


def example_create_task(jira: JiraManager):
    """Example: Create a task"""
    print("=== Creating Task ===\n")

    success, message, issue_key = jira.create_task(
        summary="Set up GitHub Actions CI/CD pipeline",
        description="""h3. Task Description

Configure GitHub Actions for automated testing and deployment.

h3. Context

Automate manual testing and deployment processes.

h3. Steps

# Create `.github/workflows/ci.yml`
# Configure PR trigger
# Add linting and testing jobs
# Create deployment workflow
# Configure secrets
# Test with draft PR

h3. Expected Outcome

* PRs automatically run CI checks
* Main branch deploys to staging
* Failed deployments notify team""",
        priority="Medium"
    )

    if success:
        print(f"Success! Created task: {issue_key}")
        print(f"Message: {message}")
    else:
        print(f"Failed: {message}")
    print()
    return issue_key if success else None


def example_get_metadata(jira: JiraManager):
    """Example: Get project metadata"""
    print("=== Retrieving Project Metadata ===\n")

    success, message, metadata = jira.get_project_metadata()

    if success and metadata:
        print(f"Project: {metadata['project_key']}")
        print(f"Issue Types: {', '.join(metadata['issue_types'])}")
        print(f"Priorities: {', '.join(metadata['priorities'])}")
        print(f"Components: {', '.join(metadata['components']) if metadata['components'] else 'None'}")
    else:
        print(f"Failed: {message}")
    print()


def main():
    """Main example function"""
    print("Jira Manager API Usage Examples")
    print("=" * 60)
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

        # Run examples
        example_get_metadata(jira)

        # Create an epic
        epic_key = example_create_epic(jira)

        # Create a story linked to the epic
        if epic_key:
            example_create_story(jira, epic_key)
        else:
            example_create_story(jira)

        # Create a task
        example_create_task(jira)

        # Create a bug
        example_create_bug(jira)

        print("=" * 60)
        print("Examples completed!")

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
