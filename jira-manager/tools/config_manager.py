import sys
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w


class ConfigManager:
    """Manages Jira configuration stored in ~/.config/jira/config.toml"""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "jira"
        self.config_file = self.config_dir / "config.toml"

    def load_config(self) -> dict:
        """Load configuration from TOML file"""
        if not self.config_file.exists():
            return {"directory_mappings": {}, "profiles": {}}

        with open(self.config_file, "rb") as f:
            return tomllib.load(f)

    def save_config(self, config: dict) -> None:
        """Save configuration to TOML file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "wb") as f:
            tomli_w.dump(config, f)

    def get_profile_for_directory(self, directory: str) -> Optional[dict]:
        """Get Jira profile configuration for a specific directory

        Args:
            directory: Absolute path to the directory

        Returns:
            Profile dict with server_url, pat, project_key or None
        """
        config = self.load_config()
        directory_mappings = config.get("directory_mappings", {})
        profiles = config.get("profiles", {})

        # Check if directory has a mapping
        profile_name = directory_mappings.get(directory)
        if not profile_name:
            return None

        # Get profile data
        return profiles.get(profile_name)

    def add_profile(
        self,
        profile_name: str,
        server_url: str,
        pat: str,
        project_key: str,
        directory: str
    ) -> None:
        """Add or update a Jira profile and map it to a directory

        Args:
            profile_name: Unique name for the profile
            server_url: Jira server URL (e.g., https://jira.example.com)
            pat: Personal Access Token
            project_key: Default project key (e.g., PROJ)
            directory: Absolute path to map to this profile
        """
        config = self.load_config()

        # Initialize structure if needed
        if "directory_mappings" not in config:
            config["directory_mappings"] = {}
        if "profiles" not in config:
            config["profiles"] = {}

        # Add profile
        config["profiles"][profile_name] = {
            "server_url": server_url,
            "pat": pat,
            "project_key": project_key
        }

        # Add directory mapping
        config["directory_mappings"][directory] = profile_name

        # Save
        self.save_config(config)

    def list_profiles(self) -> dict:
        """List all available profiles

        Returns:
            Dict of profile_name -> profile_data
        """
        config = self.load_config()
        return config.get("profiles", {})

    def get_directories_for_profile(self, profile_name: str) -> list[str]:
        """Get all directories mapped to a specific profile

        Args:
            profile_name: Name of the profile

        Returns:
            List of directory paths
        """
        config = self.load_config()
        directory_mappings = config.get("directory_mappings", {})

        return [
            directory
            for directory, name in directory_mappings.items()
            if name == profile_name
        ]
