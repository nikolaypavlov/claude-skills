---
description: "Comprehensive PR/MR review with GitHub and GitLab support"
argument-hint: "[pr-number] [aspects: code|tests|errors|comments|types|simplify|all] [parallel] [--lang en|uk] [--post inline|single|no]"
allowed-tools: ["Bash", "Glob", "Grep", "Read", "Agent", "AskUserQuestion"]
---

You are an orchestrator for comprehensive PR/MR code review. Follow these phases strictly and in order.

## Phase 1: Platform Detection

Run `git remote -v` and determine the platform:
- If any remote URL contains `github.com` -> platform is **GitHub**, use `gh` CLI
- If any remote URL contains `gitlab` (gitlab.com or self-hosted) -> platform is **GitLab**, use `glab` CLI
- If neither is detected, tell the user and stop

Verify the CLI tool is available by running `which gh` or `which glab`. If not found, show installation instructions and stop.

**GitLab `-R` format for all `glab mr` commands:**
- For gitlab.com repos: `-R group/project`
- For self-hosted: `-R gitlab.example.com/group/project`
- The `-R` flag is required when not inside the git repo directory

**GitLab `glab api` hostname:**
- `glab api` supports `--hostname gitlab.example.com` for self-hosted instances
- Auto-detects hostname when inside a git repo with configured remote

## Phase 2: PR/MR Identification and Context Gathering

### 2.1 Identify the PR/MR

Parse `$ARGUMENTS` for a PR/MR number (first numeric argument).

If no number is provided, auto-detect from current branch:
- **GitHub**: `gh pr view --json number,title,body,url,baseRefName,headRefName`
- **GitLab**: `glab mr view -F json` (returns full metadata including `diff_refs`)

If no PR/MR is found for the current branch, tell the user and stop.

### 2.2 Fetch the diff

- **GitHub**: `gh pr diff <number>`
- **GitLab**: `glab mr diff <iid>`

### 2.3 Fetch changed files list

- **GitHub**: `gh pr diff <number> --name-only`
- **GitLab**: `glab mr diff` does NOT support `--name-only`. Instead use the changes API:
  ```bash
  glab api projects/<url-encoded-path>/merge_requests/<iid>/changes --hostname <host> \
    | python3 -c "import json,sys; [print(c['new_path']) for c in json.load(sys.stdin).get('changes',[])]"
  ```

### 2.4 Fetch existing comments and discussion

This is critical context for the review agents.

**GitHub:**
```bash
# PR description, comments, and reviews
gh pr view <number> --json title,body,comments,reviews,labels

# Inline review comments
gh api repos/{owner}/{repo}/pulls/{number}/comments
```

**GitLab:**
```bash
# MR description + full metadata (includes diff_refs for inline comments)
glab mr view <iid> -R <repo> -F json

# All notes/comments - structured, filterable by type
glab mr note list <iid> -R <repo> -F json

# Filter to only diff (inline) comments
glab mr note list <iid> -R <repo> -F json --type diff

# Or via API for self-hosted with --hostname
glab api projects/<url-encoded-path>/merge_requests/<iid>/notes --hostname <host>
```

Format the comments into an "Existing Discussion" context block:
```
## Existing Discussion

### PR/MR Description
<title and body>

### Comments
- [Author] (date): <comment body>
- [Bot: jira-bot] (date): <linked issue details>
...

### Inline Review Comments
- [Author] on file.py:42 (date): <comment>
...
```

Label bot comments by checking if the author name contains patterns like: bot, jira, linear, github-actions, gitlab-ci, dependabot, renovate.

### 2.5 Extract related issue context

Scan the PR/MR description and bot comments for references to Jira or Linear issues:
- Jira patterns: `[A-Z]+-\d+` (e.g., PROJ-123), URLs containing `/browse/PROJ-123`
- Linear patterns: `[A-Z]+-\d+`, URLs containing `linear.app`

If found, include the issue key/URL and any description text from bot comments as "Related Issue Context" to pass to agents.

## Phase 3: Determine Review Scope

Parse `$ARGUMENTS` for review aspects:
- `code` - general code quality (code-reviewer agent)
- `tests` - test coverage (pr-test-analyzer agent)
- `errors` - error handling (silent-failure-hunter agent)
- `comments` - comment accuracy (comment-analyzer agent)
- `types` - type design (type-design-analyzer agent)
- `simplify` - code simplification (code-simplifier agent)
- `all` - run all applicable agents (default)

When `all` is selected, use smart selection based on changed files:
- **Always run**: code-reviewer
- **If test files exist in changes** (files matching `*test*`, `*spec*`, `*_test.*`): pr-test-analyzer
- **If comments or docstrings were changed**: comment-analyzer
- **If error handling code is present** (try/catch, except, rescue, Result types): silent-failure-hunter
- **If types/interfaces/classes/structs were added or modified**: type-design-analyzer
- **Run last**: code-simplifier (only after all other agents complete)

## Phase 4: Launch Review Agents

For each applicable agent, launch it via the Agent tool with this context in the prompt:

```
Review the following PR/MR changes:

## Diff
<full diff content>

## Changed Files
<list of changed files>

## PR/MR Description
<title and body>

## Related Issue Context
<Jira/Linear issue references and descriptions, if any>

## Existing Discussion
<formatted comments from Phase 2.4>
```

**Execution mode:**
- Default: run agents **sequentially**, one at a time
- If `$ARGUMENTS` contains `parallel`: launch all agents simultaneously using multiple Agent tool calls in a single message

## Phase 5: Main Model Validation

After ALL agents complete, collect their findings and apply these filters IN ORDER:

### 5.1 File:line check
Drop any finding that does not include a `path/to/file.ext:LINE` reference. No exceptions.

### 5.2 Deduplication
If multiple agents reported the same issue (same file, same line range, same problem category), merge them into a single finding. Credit all contributing agents.

### 5.3 Confidence filter
Drop findings with confidence score below 80.

### 5.4 Diff verification
Verify each finding references lines that actually appear in the diff. Drop findings about code that was not changed in this PR/MR.

### 5.5 Relevance filter
Drop speculative findings that use hedging language without concrete evidence: "might", "could possibly", "may or may not", "potentially problematic".

### 5.6 By-design filter
If the PR/MR has related Jira/Linear issue context (from Phase 2.5), analyze each remaining finding:
- Does the finding describe behavior that matches acceptance criteria from the issue?
- Does the finding flag a trade-off that was explicitly mentioned in the PR description?
- Does the finding contradict a design decision documented in the issue or discussion?

If yes to any of the above, drop the finding - it is an intentional design choice, not a bug.

## Phase 6: Format Final Report

### 6.1 Determine language

Check `$ARGUMENTS` for `--lang en` or `--lang uk`.
If not specified, detect from the conversation language (if user writes in Ukrainian, use Ukrainian).
If still ambiguous, default to English.

### 6.2 Format the report

Structure the validated findings as:

```markdown
## Code Review - PR/MR #N: <title>

### Critical Issues (X)
- **[agent-name]** `file/path.ext:LINE` - Description of the issue. **Recommendation**: How to fix it.

### Important Issues (X)
- **[agent-name]** `file/path.ext:LINE` - Description of the issue. **Recommendation**: How to fix it.

### Suggestions (X)
- **[agent-name]** `file/path.ext:LINE` - Description of the issue. **Recommendation**: How to fix it.
```

Rules:
- No "Strengths" section. Only concrete issues.
- Every entry MUST have `file/path.ext:LINE` reference.
- Keep descriptions concise and actionable.
- If no issues were found after validation, report: "No issues found. The changes look good."

## Phase 7: Display and Post

### 7.1 Display the report

ALWAYS output the full formatted review text to the user. This is mandatory before any posting.

### 7.2 Determine posting action

Check `$ARGUMENTS` for `--post` flag:
- `--post inline` - post inline comments without asking (use language from `--lang`, default English)
- `--post single` - post as single comment without asking (use language from `--lang`, default English)
- `--post no` - do not post, just display the report

If `--post` is NOT specified, use the AskUserQuestion tool to ask the user:

Question: "Post this review to the PR/MR?"
Options:
- "Post inline comments (English)" - each finding as a separate inline comment on the corresponding file/line
- "Post inline comments (Ukrainian)" - same as above but translated to Ukrainian
- "Post as single comment (English)" - one top-level comment with the full review
- "Post as single comment (Ukrainian)" - same as above but translated to Ukrainian
- "Do not post"

NEVER post comments without the user's explicit approval via AskUserQuestion or the `--post` flag.

### 7.3 Post (if approved)

Translate the review to the selected language if needed.

**If "single comment" was selected**, post the full review as one top-level comment:
- **GitHub**: `gh pr comment <number> --body "<full review markdown>"`
- **GitLab**: `glab mr note <iid> -R <repo> -m "<full review markdown>" --unique`

The `--unique` flag (GitLab) prevents duplicate comments when re-running the review.

**If "inline comments" was selected**, post each finding separately:

**GitHub - Create a PR review with inline comments:**

Build a JSON payload and post it:
```bash
# First get the latest commit SHA
COMMIT_SHA=$(gh pr view <number> --json commits --jq '.commits[-1].oid')

# Create the review with inline comments
echo '<json_payload>' | gh api repos/{owner}/{repo}/pulls/{number}/reviews \
  --method POST --input -
```

JSON payload structure:
```json
{
  "commit_id": "<latest_commit_sha>",
  "body": "## Code Review Summary\n\n<brief summary of findings>",
  "event": "COMMENT",
  "comments": [
    {
      "path": "relative/path/to/file.ext",
      "line": 42,
      "body": "**[agent-name]** SEVERITY: Description.\n\n**Recommendation**: Fix suggestion."
    }
  ]
}
```

**GitLab - Create inline discussions:**

For each finding, create a separate discussion:
```bash
# Get diff_refs from MR metadata (already fetched in Phase 2.1 via glab mr view -F json)
# Extract: diff_refs.base_sha, diff_refs.head_sha, diff_refs.start_sha

# Post each inline comment as a discussion
# Use --hostname for self-hosted GitLab instances
glab api projects/<url-encoded-path>/merge_requests/<iid>/discussions \
  --hostname <host> \
  --method POST \
  -f body="**[agent-name]** SEVERITY: Description.\n\n**Recommendation**: Fix suggestion." \
  -f "position[position_type]=text" \
  -f "position[new_path]=relative/path/to/file.ext" \
  -f "position[new_line]=42" \
  -f "position[base_sha]=$BASE_SHA" \
  -f "position[head_sha]=$HEAD_SHA" \
  -f "position[start_sha]=$START_SHA"
```

After posting, confirm to the user how many comments were posted and provide a link to the PR/MR.
