# PR Reviewer

Comprehensive PR/MR code review plugin for Claude Code with GitHub and GitLab support.

## Features

- Auto-detects GitHub (`gh`) or GitLab (`glab`) from git remotes
- Fetches existing PR/MR comments and discussion as context for review agents
- Recognizes Jira/Linear issue references and filters out by-design findings
- 7 specialized review agents: code quality, test coverage, error handling, comment accuracy, type design, code simplification, infrastructure
- Main model validates all findings: enforces file:line references, deduplicates, filters weak/speculative results
- Posts review with explicit user permission: inline comments per finding or single top-level comment
- Supports English and Ukrainian output
- Self-hosted GitLab support via `glab -R hostname/group/project`

## Usage

```bash
# Full review of current branch's PR/MR (auto-detect platform)
/pr-reviewer:review-pr

# Review a specific PR/MR number
/pr-reviewer:review-pr 123

# Run only specific review aspects
/pr-reviewer:review-pr tests errors
/pr-reviewer:review-pr code types

# Run all agents in parallel (faster)
/pr-reviewer:review-pr all parallel

# Specify output language
/pr-reviewer:review-pr --lang uk
/pr-reviewer:review-pr 123 code --lang en
```

## Review Aspects

| Aspect | Agent | What it checks |
|--------|-------|----------------|
| `code` | code-reviewer | Project guidelines, bugs, code quality |
| `tests` | pr-test-analyzer | Test coverage gaps and test quality |
| `errors` | silent-failure-hunter | Silent failures, catch blocks, error handling |
| `comments` | comment-analyzer | Comment accuracy, outdated docs |
| `types` | type-design-analyzer | Type invariants, encapsulation |
| `simplify` | code-simplifier | Code clarity and simplification |
| `infra` | infra-reviewer | Terraform, Kubernetes, Helm, CI pipelines |
| `all` | Smart selection | Picks agents based on changed files (default) |

## Workflow

1. Detects platform (GitHub/GitLab) from `git remote -v`
2. Fetches PR/MR metadata, diff, existing comments, and linked issue context
3. Launches applicable review agents with full context
4. Validates all findings: enforces file:line, deduplicates, filters low-confidence, removes by-design items
5. Displays formatted report to user
6. Asks permission before posting to PR/MR (inline comments or single comment, EN/UK)

## GitLab Notes

- For self-hosted GitLab: `glab auth login --hostname gitlab.example.com --token <token>`
- All `glab mr` commands use `-R gitlab.example.com/group/project` for remote repos
- `glab api` uses `--hostname gitlab.example.com` for self-hosted instances
- `glab mr diff` does not support `--name-only` - the plugin uses the changes API instead
- `glab mr note --unique` prevents duplicate comments when re-running review

## Requirements

- `gh` CLI for GitHub repositories
- `glab` CLI for GitLab repositories
- Authenticated session for the respective CLI tool
