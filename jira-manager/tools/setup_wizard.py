#!/usr/bin/env python3
import sys
from pathlib import Path
from config_manager import ConfigManager
from jira_client import JiraManager


def run_setup_wizard(directory: str) -> bool:
    """Run interactive setup wizard to configure Jira for a directory

    Args:
        directory: Absolute path to the directory to configure

    Returns:
        True if setup was successful, False otherwise
    """
    print("=" * 60)
    print("Jira Manager Setup Wizard")
    print("=" * 60)
    print()
    print(f"Configuring Jira for directory: {directory}")
    print()

    # Collect information
    print("Please provide your Jira Server details:")
    print()

    server_url = input("Jira Server URL (e.g., https://jira.example.com): ").strip()
    if not server_url:
        print("Error: Server URL is required")
        return False

    pat = input("Personal Access Token: ").strip()
    if not pat:
        print("Error: Personal Access Token is required")
        return False

    project_key = input("Default Project Key (e.g., PROJ): ").strip().upper()
    if not project_key:
        print("Error: Project key is required")
        return False

    # Generate profile name from project key
    profile_name = f"{project_key.lower()}_profile"
    custom_name = input(f"Profile name [{profile_name}]: ").strip()
    if custom_name:
        profile_name = custom_name

    print()
    print("Testing connection to Jira Server...")

    # Test connection
    try:
        jira_manager = JiraManager(server_url, pat, project_key)
        success, message = jira_manager.test_connection()

        if not success:
            print(f"Connection test failed: {message}")
            retry = input("Would you like to retry with different credentials? (y/n): ").strip().lower()
            if retry == 'y':
                return run_setup_wizard(directory)
            return False

        print(f"Success! {message}")
        print()

        # Get project metadata to verify access
        success, msg, metadata = jira_manager.get_project_metadata()
        if success and metadata:
            print(f"Project: {metadata['project_key']}")
            print(f"Available issue types: {', '.join(metadata['issue_types'])}")
            print()

    except Exception as e:
        print(f"Error testing connection: {str(e)}")
        return False

    # Save configuration
    print("Saving configuration...")
    try:
        config_manager = ConfigManager()
        config_manager.add_profile(
            profile_name=profile_name,
            server_url=server_url,
            pat=pat,
            project_key=project_key,
            directory=directory
        )

        config_file = config_manager.config_file
        print(f"Configuration saved to: {config_file}")
        print()
        print("Setup complete! You can now create Jira tickets from this directory.")
        print()
        return True

    except Exception as e:
        print(f"Error saving configuration: {str(e)}")
        return False


def main():
    """Main entry point for setup wizard"""
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = Path.cwd().resolve().as_posix()

    success = run_setup_wizard(directory)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
