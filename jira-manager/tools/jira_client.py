from typing import Optional
from jira import JIRA
from jira.exceptions import JIRAError


class JiraManager:
    """Manages Jira Server API interactions using Personal Access Tokens"""

    def __init__(self, server_url: str, pat: str, project_key: str, user_email: Optional[str] = None):
        """Initialize Jira client with PAT authentication

        Args:
            server_url: Jira server URL (e.g., https://jira.example.com)
            pat: Personal Access Token for authentication (Server) or API token (Cloud)
            project_key: Default project key (e.g., PROJ)
            user_email: User email for Jira Cloud basic auth (required for Cloud)
        """
        self.server_url = server_url.rstrip("/")
        self.project_key = project_key

        # Determine if Jira Cloud or Server
        is_cloud = "atlassian.net" in server_url.lower()

        # Initialize JIRA client with appropriate authentication
        if is_cloud and user_email:
            # Jira Cloud uses Basic Auth (email, API token)
            self.client = JIRA(server=self.server_url, basic_auth=(user_email, pat))
        else:
            # Jira Server uses PAT token authentication (original logic)
            self.client = JIRA(server=self.server_url, token_auth=pat)

        # OLD LOGIC (kept for reference - can revert if needed):
        # self.client = JIRA(server=self.server_url, token_auth=pat)

    def test_connection(self) -> tuple[bool, str]:
        """Test connection to Jira server

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Try to get server info
            server_info = self.client.server_info()
            version = server_info.get("version", "unknown")
            return True, f"Connected to Jira Server v{version}"
        except JIRAError as e:
            return False, f"Connection failed: {e.text}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def create_bug(
        self,
        summary: str,
        description: str,
        priority: Optional[str] = None,
        **additional_fields
    ) -> tuple[bool, str, Optional[str]]:
        """Create a bug issue

        Args:
            summary: Issue summary
            description: Issue description (Jira Wiki Markup)
            priority: Priority name (e.g., "High", "Medium", "Low")
            **additional_fields: Additional Jira fields

        Returns:
            Tuple of (success: bool, message: str, issue_key: Optional[str])
        """
        return self._create_issue("Bug", summary, description, priority, **additional_fields)

    def create_task(
        self,
        summary: str,
        description: str,
        priority: Optional[str] = None,
        **additional_fields
    ) -> tuple[bool, str, Optional[str]]:
        """Create a task issue

        Args:
            summary: Issue summary
            description: Issue description (Jira Wiki Markup)
            priority: Priority name (e.g., "High", "Medium", "Low")
            **additional_fields: Additional Jira fields

        Returns:
            Tuple of (success: bool, message: str, issue_key: Optional[str])
        """
        return self._create_issue("Task", summary, description, priority, **additional_fields)

    def create_story(
        self,
        summary: str,
        description: str,
        priority: Optional[str] = None,
        epic_key: Optional[str] = None,
        **additional_fields
    ) -> tuple[bool, str, Optional[str]]:
        """Create a story issue

        Args:
            summary: Issue summary
            description: Issue description (Jira Wiki Markup)
            priority: Priority name (e.g., "High", "Medium", "Low")
            epic_key: Parent epic key (e.g., "PROJ-123")
            **additional_fields: Additional Jira fields

        Returns:
            Tuple of (success: bool, message: str, issue_key: Optional[str])
        """
        if epic_key:
            additional_fields["parent"] = {"key": epic_key}

        return self._create_issue("Story", summary, description, priority, **additional_fields)

    def create_epic(
        self,
        summary: str,
        description: str,
        epic_name: Optional[str] = None,
        **additional_fields
    ) -> tuple[bool, str, Optional[str]]:
        """Create an epic issue

        Args:
            summary: Issue summary
            description: Issue description (Jira Wiki Markup)
            epic_name: Epic name (customField - may vary by Jira configuration)
            **additional_fields: Additional Jira fields

        Returns:
            Tuple of (success: bool, message: str, issue_key: Optional[str])
        """
        # Note: Epic name field varies by Jira configuration
        # It might be customfield_10011, customfield_10003, etc.
        if epic_name and "customfield_epic_name" in additional_fields:
            field_id = additional_fields.pop("customfield_epic_name")
            additional_fields[field_id] = epic_name

        return self._create_issue("Epic", summary, description, None, **additional_fields)

    def _create_issue(
        self,
        issue_type: str,
        summary: str,
        description: str,
        priority: Optional[str] = None,
        **additional_fields
    ) -> tuple[bool, str, Optional[str]]:
        """Internal method to create an issue

        Args:
            issue_type: Issue type name
            summary: Issue summary
            description: Issue description
            priority: Priority name
            **additional_fields: Additional Jira fields

        Returns:
            Tuple of (success: bool, message: str, issue_key: Optional[str])
        """
        try:
            fields = {
                "project": {"key": self.project_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type},
            }

            if priority:
                fields["priority"] = {"name": priority}

            # Merge additional fields
            fields.update(additional_fields)

            # Create issue
            issue = self.client.create_issue(fields=fields)
            issue_url = f"{self.server_url}/browse/{issue.key}"

            return True, f"Created {issue_type} {issue.key}: {issue_url}", issue.key

        except JIRAError as e:
            error_msg = f"Failed to create {issue_type}: {e.text}"
            return False, error_msg, None
        except Exception as e:
            error_msg = f"Failed to create {issue_type}: {str(e)}"
            return False, error_msg, None

    def add_to_epic(self, issue_key: str, epic_key: str) -> tuple[bool, str]:
        """Add an issue to an epic

        Args:
            issue_key: Issue key to add (e.g., "PROJ-124")
            epic_key: Epic key (e.g., "PROJ-123")

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            self.client.add_issues_to_epic(epic_key, [issue_key])
            return True, f"Added {issue_key} to epic {epic_key}"
        except JIRAError as e:
            return False, f"Failed to add to epic: {e.text}"
        except Exception as e:
            return False, f"Failed to add to epic: {str(e)}"

    def get_project_metadata(self) -> tuple[bool, str, Optional[dict]]:
        """Get project metadata (issue types, priorities, components)

        Returns:
            Tuple of (success: bool, message: str, metadata: Optional[dict])
        """
        try:
            # Get issue types
            issue_types = [it.name for it in self.client.issue_types()]

            # Get priorities
            priorities = [p.name for p in self.client.priorities()]

            # Get project components
            project = self.client.project(self.project_key)
            components = [c.name for c in self.client.project_components(project)]

            metadata = {
                "issue_types": issue_types,
                "priorities": priorities,
                "components": components,
                "project_key": self.project_key,
            }

            return True, "Retrieved project metadata", metadata

        except JIRAError as e:
            return False, f"Failed to get metadata: {e.text}", None
        except Exception as e:
            return False, f"Failed to get metadata: {str(e)}", None

    def search_issues(
        self,
        jql_query: str,
        max_results: int = 50,
        fields: Optional[list] = None
    ) -> tuple[bool, str, Optional[list]]:
        """Search for issues using JQL (Jira Query Language)

        Args:
            jql_query: JQL search query (e.g., "text ~ 'login' AND status = Open")
            max_results: Maximum number of results to return (default: 50)
            fields: List of fields to retrieve (default: all fields)

        Returns:
            Tuple of (success: bool, message: str, issues: Optional[list])
            issues is a list of dicts with issue data
        """
        try:
            # Search issues
            issues = self.client.search_issues(
                jql_query,
                maxResults=max_results,
                fields=fields or "*all"
            )

            # Convert to list of dicts
            issue_list = []
            for issue in issues:
                issue_list.append({
                    "key": issue.key,
                    "summary": issue.fields.summary,
                    "status": issue.fields.status.name,
                    "issue_type": issue.fields.issuetype.name,
                    "priority": issue.fields.priority.name if hasattr(issue.fields, 'priority') and issue.fields.priority else None,
                    "description": issue.fields.description or "",
                    "url": f"{self.server_url}/browse/{issue.key}"
                })

            return True, f"Found {len(issue_list)} issues", issue_list

        except JIRAError as e:
            return False, f"Search failed: {e.text}", None
        except Exception as e:
            return False, f"Search failed: {str(e)}", None

    def get_issue(self, issue_key: str) -> tuple[bool, str, Optional[dict]]:
        """Get detailed information about a specific issue

        Args:
            issue_key: Issue key (e.g., "PROJ-123")

        Returns:
            Tuple of (success: bool, message: str, issue_data: Optional[dict])
        """
        try:
            issue = self.client.issue(issue_key)

            issue_data = {
                "key": issue.key,
                "summary": issue.fields.summary,
                "description": issue.fields.description or "",
                "status": issue.fields.status.name,
                "issue_type": issue.fields.issuetype.name,
                "priority": issue.fields.priority.name if hasattr(issue.fields, 'priority') and issue.fields.priority else None,
                "created": str(issue.fields.created),
                "updated": str(issue.fields.updated),
                "reporter": issue.fields.reporter.displayName if hasattr(issue.fields, 'reporter') and issue.fields.reporter else None,
                "url": f"{self.server_url}/browse/{issue.key}"
            }

            # Add parent/epic if exists
            if hasattr(issue.fields, 'parent') and issue.fields.parent:
                issue_data["parent"] = issue.fields.parent.key

            return True, f"Retrieved issue {issue_key}", issue_data

        except JIRAError as e:
            return False, f"Failed to get issue: {e.text}", None
        except Exception as e:
            return False, f"Failed to get issue: {str(e)}", None

    def update_issue(
        self,
        issue_key: str,
        fields: dict
    ) -> tuple[bool, str]:
        """Update fields of an existing issue

        Args:
            issue_key: Issue key (e.g., "PROJ-123")
            fields: Dictionary of fields to update
                Examples:
                - {"summary": "New summary"}
                - {"priority": {"name": "High"}}
                - {"description": "Updated description"}

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            issue = self.client.issue(issue_key)
            issue.update(fields=fields)

            return True, f"Updated issue {issue_key}"

        except JIRAError as e:
            return False, f"Failed to update issue: {e.text}"
        except Exception as e:
            return False, f"Failed to update issue: {str(e)}"

    def add_comment(
        self,
        issue_key: str,
        comment_text: str
    ) -> tuple[bool, str]:
        """Add a comment to an issue

        Args:
            issue_key: Issue key (e.g., "PROJ-123")
            comment_text: Comment text (supports Jira Wiki Markup)

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            self.client.add_comment(issue_key, comment_text)
            return True, f"Added comment to {issue_key}"

        except JIRAError as e:
            return False, f"Failed to add comment: {e.text}"
        except Exception as e:
            return False, f"Failed to add comment: {str(e)}"

    def get_issue_transitions(
        self,
        issue_key: str
    ) -> tuple[bool, str, Optional[list]]:
        """Get available transitions (status changes) for an issue

        Args:
            issue_key: Issue key (e.g., "PROJ-123")

        Returns:
            Tuple of (success: bool, message: str, transitions: Optional[list])
            transitions is a list of dicts with id, name
        """
        try:
            transitions = self.client.transitions(issue_key)

            transition_list = [
                {"id": t["id"], "name": t["name"]}
                for t in transitions
            ]

            return True, f"Retrieved {len(transition_list)} transitions", transition_list

        except JIRAError as e:
            return False, f"Failed to get transitions: {e.text}", None
        except Exception as e:
            return False, f"Failed to get transitions: {str(e)}", None

    def transition_issue(
        self,
        issue_key: str,
        transition_name: str
    ) -> tuple[bool, str]:
        """Change the status of an issue (transition to new status)

        Args:
            issue_key: Issue key (e.g., "PROJ-123")
            transition_name: Name of the transition (e.g., "In Progress", "Done")
                Use get_issue_transitions() to see available transitions

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Get available transitions
            transitions = self.client.transitions(issue_key)

            # Find matching transition
            transition_id = None
            for t in transitions:
                if t["name"].lower() == transition_name.lower():
                    transition_id = t["id"]
                    break

            if not transition_id:
                available = [t["name"] for t in transitions]
                return False, f"Transition '{transition_name}' not found. Available: {', '.join(available)}"

            # Execute transition
            self.client.transition_issue(issue_key, transition_id)
            return True, f"Transitioned {issue_key} to '{transition_name}'"

        except JIRAError as e:
            return False, f"Failed to transition issue: {e.text}"
        except Exception as e:
            return False, f"Failed to transition issue: {str(e)}"
