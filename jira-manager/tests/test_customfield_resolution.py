"""Tests for Epic Name / Epic Link customfield auto-discovery in JiraManager.

These tests verify the fixes for two Jira Server 9.12+ regressions:

1. create_epic must populate the Epic Name customfield discovered at runtime
   from jira.fields() rather than requiring the caller to know the numeric
   field ID up front.
2. create_story must link to its parent Epic via the Epic Link customfield on
   Jira Server (classic Epics), and fall back to `parent` only when Epic Link
   does not exist on the instance (Jira Cloud Next-Gen / Team-Managed).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from jira_client import JiraManager  # noqa: E402


CLASSIC_SERVER_FIELDS = [
    {"id": "summary", "name": "Summary", "custom": False},
    {"id": "customfield_10103", "name": "Epic Name", "custom": True},
    {"id": "customfield_10101", "name": "Epic Link", "custom": True},
    {"id": "customfield_10200", "name": "Sprint", "custom": True},
]

NEXT_GEN_CLOUD_FIELDS = [
    {"id": "summary", "name": "Summary", "custom": False},
    {"id": "parent", "name": "Parent", "custom": False},
    {"id": "customfield_10999", "name": "Story Points", "custom": True},
]


def _build_manager(fields_payload):
    """Construct a JiraManager whose underlying JIRA client is mocked."""
    with patch("jira_client.JIRA") as jira_ctor:
        client = MagicMock()
        client.fields.return_value = fields_payload
        jira_ctor.return_value = client
        manager = JiraManager(
            server_url="https://jira.example.com",
            pat="dummy-pat",
            project_key="ML",
        )
    manager.client.fields.return_value = fields_payload
    return manager


class ClassicServerCustomfieldsTest(unittest.TestCase):
    """Jira Server 9.12+ with classic Epics exposes Epic Name and Epic Link."""

    def test_create_epic_populates_epic_name_customfield(self):
        manager = _build_manager(CLASSIC_SERVER_FIELDS)
        created = MagicMock(key="ML-1000")
        manager.client.create_issue.return_value = created

        ok, msg, key = manager.create_epic(
            summary="Strybo MCP Phase 5 - Provisioning private replica",
            description="...",
            epic_name="Strybo MCP Phase 5",
        )

        self.assertTrue(ok, msg)
        self.assertEqual(key, "ML-1000")
        fields = manager.client.create_issue.call_args.kwargs["fields"]
        self.assertEqual(fields["customfield_10103"], "Strybo MCP Phase 5")
        self.assertEqual(fields["issuetype"], {"name": "Epic"})

    def test_create_epic_falls_back_to_summary_when_epic_name_missing(self):
        manager = _build_manager(CLASSIC_SERVER_FIELDS)
        manager.client.create_issue.return_value = MagicMock(key="ML-1001")

        manager.create_epic(
            summary="Default Epic Name From Summary",
            description="...",
        )

        fields = manager.client.create_issue.call_args.kwargs["fields"]
        self.assertEqual(
            fields["customfield_10103"],
            "Default Epic Name From Summary",
        )

    def test_create_story_uses_epic_link_customfield_not_parent(self):
        manager = _build_manager(CLASSIC_SERVER_FIELDS)
        manager.client.create_issue.return_value = MagicMock(key="ML-1500")

        ok, msg, key = manager.create_story(
            summary="Test Story",
            description="...",
            epic_key="ML-740",
        )

        self.assertTrue(ok, msg)
        self.assertEqual(key, "ML-1500")
        fields = manager.client.create_issue.call_args.kwargs["fields"]
        self.assertEqual(fields["customfield_10101"], "ML-740")
        self.assertNotIn("parent", fields)

    def test_fields_call_is_cached_across_invocations(self):
        manager = _build_manager(CLASSIC_SERVER_FIELDS)
        manager.client.create_issue.return_value = MagicMock(key="ML-2000")

        manager.create_epic(summary="E1", description="...")
        manager.create_story(summary="S1", description="...", epic_key="ML-2000")
        manager.create_story(summary="S2", description="...", epic_key="ML-2000")

        self.assertEqual(manager.client.fields.call_count, 1)


class NextGenCloudFallbackTest(unittest.TestCase):
    """Jira Cloud Next-Gen / Team-Managed has no Epic Link customfield."""

    def test_create_story_falls_back_to_parent_when_no_epic_link(self):
        manager = _build_manager(NEXT_GEN_CLOUD_FIELDS)
        manager.client.create_issue.return_value = MagicMock(key="NG-200")

        ok, msg, key = manager.create_story(
            summary="Next-Gen Story",
            description="...",
            epic_key="NG-1",
        )

        self.assertTrue(ok, msg)
        self.assertEqual(key, "NG-200")
        fields = manager.client.create_issue.call_args.kwargs["fields"]
        self.assertEqual(fields["parent"], {"key": "NG-1"})
        self.assertNotIn("customfield_10101", fields)

    def test_create_epic_skips_epic_name_when_field_absent(self):
        manager = _build_manager(NEXT_GEN_CLOUD_FIELDS)
        manager.client.create_issue.return_value = MagicMock(key="NG-1")

        manager.create_epic(
            summary="Next-Gen Epic",
            description="...",
            epic_name="Ignored",
        )

        fields = manager.client.create_issue.call_args.kwargs["fields"]
        for key in fields:
            self.assertFalse(
                key.startswith("customfield_") and key.endswith("epic_name"),
                f"Unexpected epic-name customfield set: {key}",
            )


if __name__ == "__main__":
    unittest.main()
