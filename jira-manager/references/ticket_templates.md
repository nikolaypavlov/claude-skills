# Jira Issue Templates

These templates are used for creating consistent, high-quality Jira issues.

## Epic Template

```markdown
**Epic Goal:**
[Clear statement of what this epic aims to achieve]

**Business Value:**
- [Key business benefit 1]
- [Key business benefit 2]
- [Key business benefit 3]

**Scope:**
- [Major capability 1]
- [Major capability 2]
- [Major capability 3]

**Success Criteria:**
- [Measurable criterion 1]
- [Measurable criterion 2]
- [Measurable criterion 3]

**Dependencies:**
- [Technical or team dependency 1]
- [Technical or team dependency 2]
```

**Summary Format**: `[Feature Name] - [Brief Description]`  
Example: `ICP Builder - Ideal Customer Profile Creation`

---

## Story Template

```markdown
**User Story:**
As a [user role], I want to [action/capability], so that [benefit/value].

**Acceptance Criteria:**

1. [Feature/Capability Name]
   - [Specific, testable requirement 1]
   - [Specific, testable requirement 2]
   - [Specific, testable requirement 3]

2. [Feature/Capability Name]
   - [Specific, testable requirement 1]
   - [Specific, testable requirement 2]

3. [Feature/Capability Name]
   - [Specific, testable requirement 1]
   - [Specific, testable requirement 2]

[Continue for all major features/capabilities]

**Technical Notes:**
- Component/File: [Component name or file path]
- Key implementation details: [Brief technical context]
- API endpoints: [If applicable]
- State management: [If applicable]

**Definition of Done:**
- [Completion criterion 1]
- [Completion criterion 2]
- All acceptance criteria met
- [Any additional completion requirements]
```

**Summary Format**: `[Action-oriented description of the feature]`  
Example: `Step-by-step questionnaire navigation and progress tracking`

**Best Practices:**
- Group acceptance criteria by logical feature/capability sections
- Make criteria specific and testable
- Include technical context for developers
- Link to parent Epic using `additional_fields: {"parent": {"key": "KEY-N"}}`

---

## Task Template

```markdown
**Task Description:**
[Clear description of what needs to be done]

**Context:**
[Why this task is needed - link to story/epic if applicable]

**Steps:**
1. [Specific step 1]
2. [Specific step 2]
3. [Specific step 3]

**Expected Outcome:**
[What should be the result when task is complete]

**Resources/References:**
- [Link or reference 1]
- [Link or reference 2]

**Notes:**
- [Any additional context or constraints]
```

**Summary Format**: `[Action verb] [specific task]`  
Example: `Set up branch protection rules for dev and release`

---

## Bug Template

```markdown
**Bug Description:**
[Clear description of the bug]

**Steps to Reproduce:**
1. [Step 1]
2. [Step 2]
3. [Step 3]

**Expected Behavior:**
[What should happen]

**Actual Behavior:**
[What actually happens]

**Environment:**
- Browser/Device: [e.g., Chrome 118, Safari iOS 17]
- User Role: [e.g., Marketer, Admin]
- Date/Time: [When the bug was discovered]

**Screenshots/Logs:**
[Attach or describe any relevant screenshots or error logs]

**Severity:**
[Critical / High / Medium / Low]

**Suggested Fix:**
[If known, suggest potential solution]
```

**Summary Format**: `[Component/Feature] - [Brief bug description]`  
Example: `ICP Builder - AI suggestions not loading after navigation`

