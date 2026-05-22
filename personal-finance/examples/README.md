# personal-finance examples

Opt-in artifacts for users who want their data to stay fresh and backed up outside the Claude conversation. None of these ship with the plugin install - copy what you want, edit the paths marked `CHANGE_ME`, and wire it yourself.

## `backup_db.sh`

Online SQLite backup of `~/finances/data.db` followed by an `rclone copy` to a remote you control. Uses `sqlite3 .backup` (WAL-safe, no write lock) plus local retention pruning. Run it on a cron / launchd schedule of your choice. See the header comment for the env-var contract.

## `com.monobank-mcp.sync.plist`

macOS LaunchAgent that runs `monobank-mcp sync` once an hour. Useful if you want yesterday's transactions to be in the store BEFORE you open Claude rather than waiting for the in-conversation `ensure_synced` call. Optional - the in-conversation path always works.

Load with `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.monobank-mcp.sync.plist` after editing the two `CHANGE_ME` paths.
