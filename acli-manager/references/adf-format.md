# Atlassian Document Format (ADF) Reference

ADF is the JSON format Jira Cloud uses for rich text content (descriptions, comments). This is the **only way** to get formatted descriptions via acli -- the `--description` and `--description-file` flags always produce plain text.

Full JSON schema: http://go.atlassian.com/adf-json-schema (~3000 lines -- use only as a validation reference, not as a starting point).

## How to use ADF with acli

ADF works through the `--from-json` flag on `create` and `edit` commands:

```bash
# Create with ADF description
acli jira workitem create --from-json workitem.json

# Edit existing item's description
acli jira workitem edit --from-json edit.json --yes
```

Generate JSON templates to see the expected structure:

```bash
acli jira workitem create --generate-json
acli jira workitem edit --generate-json
```

## Document structure

Every ADF document has the same wrapper:

```json
{
  "type": "doc",
  "version": 1,
  "content": [
    // ... array of block nodes
  ]
}
```

## Block nodes

### Heading

```json
{
  "type": "heading",
  "attrs": {"level": 3},
  "content": [{"type": "text", "text": "Section Title"}]
}
```

Levels: 1-6 (like HTML h1-h6).

### Paragraph

```json
{
  "type": "paragraph",
  "content": [{"type": "text", "text": "Regular paragraph text."}]
}
```

### Bullet list

```json
{
  "type": "bulletList",
  "content": [
    {
      "type": "listItem",
      "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "First item"}]}
      ]
    },
    {
      "type": "listItem",
      "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Second item"}]}
      ]
    }
  ]
}
```

Each listItem must contain a paragraph node.

### Ordered list

```json
{
  "type": "orderedList",
  "content": [
    {
      "type": "listItem",
      "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Step one"}]}
      ]
    }
  ]
}
```

### Code block

```json
{
  "type": "codeBlock",
  "attrs": {"language": "bash"},
  "content": [{"type": "text", "text": "echo 'hello world'"}]
}
```

### Rule (horizontal divider)

```json
{"type": "rule"}
```

## Inline marks (text formatting)

Marks are applied to text nodes within paragraphs or headings.

### Bold

```json
{"type": "text", "text": "Bold text", "marks": [{"type": "strong"}]}
```

### Italic

```json
{"type": "text", "text": "Italic text", "marks": [{"type": "em"}]}
```

### Code (inline)

```json
{"type": "text", "text": "code_snippet", "marks": [{"type": "code"}]}
```

### Link

```json
{"type": "text", "text": "Click here", "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}]}
```

### Combined marks

```json
{"type": "text", "text": "Bold and italic", "marks": [{"type": "strong"}, {"type": "em"}]}
```

## Create JSON structure

For `acli jira workitem create --from-json`:

```json
{
  "summary": "Work item title",
  "projectKey": "PROJ",
  "type": "Story",
  "parentIssueId": 10001,
  "assignee": "user@example.com",
  "label": ["label1", "label2"],
  "description": {
    "type": "doc",
    "version": 1,
    "content": [...]
  }
}
```

> **`--from-json` field name gotchas**: The JSON field names differ from CLI flag names. Use `type` (not `issueType`) and `parentIssueId` with a **numeric ID** (not an issue key like `PROJ-1`). To get the numeric ID of a parent issue: `acli jira workitem view PROJ-1 --json | jq '.id'`. When in doubt, run `acli jira workitem create --generate-json` to see the exact field names expected.

## Edit JSON structure

For `acli jira workitem edit --from-json`:

```json
{
  "issues": ["KEY-1", "KEY-2"],
  "description": {
    "type": "doc",
    "version": 1,
    "content": [...]
  }
}
```

You can also update other fields:

```json
{
  "issues": ["KEY-1"],
  "summary": "Updated title",
  "assignee": "user@example.com",
  "labelsToAdd": ["new-label"],
  "labelsToRemove": ["old-label"],
  "type": "Story"
}
```

## Full example: User story with formatted description

```json
{
  "issues": ["PROJ-42"],
  "description": {
    "type": "doc",
    "version": 1,
    "content": [
      {
        "type": "heading",
        "attrs": {"level": 3},
        "content": [{"type": "text", "text": "User Story"}]
      },
      {
        "type": "paragraph",
        "content": [{"type": "text", "text": "As a user, I want to reset my password, so that I can regain access to my account."}]
      },
      {
        "type": "heading",
        "attrs": {"level": 3},
        "content": [{"type": "text", "text": "Acceptance Criteria"}]
      },
      {
        "type": "paragraph",
        "content": [{"type": "text", "text": "Password reset flow", "marks": [{"type": "strong"}]}]
      },
      {
        "type": "bulletList",
        "content": [
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "User clicks \"Forgot password\" on login page"}]}]},
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Email with reset link sent within 30 seconds"}]}]},
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Reset link expires after 24 hours"}]}]}
        ]
      },
      {
        "type": "paragraph",
        "content": [{"type": "text", "text": "Validation", "marks": [{"type": "strong"}]}]
      },
      {
        "type": "bulletList",
        "content": [
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "New password must meet complexity requirements"}]}]},
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Cannot reuse last 5 passwords"}]}]}
        ]
      },
      {
        "type": "heading",
        "attrs": {"level": 3},
        "content": [{"type": "text", "text": "Definition of Done"}]
      },
      {
        "type": "bulletList",
        "content": [
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Unit tests pass"}]}]},
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "E2E test for full reset flow"}]}]},
          {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Security review completed"}]}]}
        ]
      },
      {
        "type": "heading",
        "attrs": {"level": 3},
        "content": [{"type": "text", "text": "Estimate"}]
      },
      {
        "type": "paragraph",
        "content": [{"type": "text", "text": "3 days"}]
      }
    ]
  }
}
```
