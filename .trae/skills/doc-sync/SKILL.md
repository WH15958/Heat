---
name: "doc-sync"
description: "Synchronizes Heat project documentation. Invoke when user asks to update docs, or types /git, or after significant code changes."
---

# Documentation Sync for Heat Project

Synchronize all project documentation to reflect the latest code changes. This skill enforces the documentation update process defined in heat.md section 8.2.

## When to Invoke

- When user asks to update documentation
- When user types `/git`
- After significant code changes that affect user-facing features or APIs
- When user asks to commit and push

## Documentation Update Process

### Step 1: Analyze Changes

Identify what changed since the last documentation update:

1. Run `git log --oneline -10` to see recent commits
2. Review the current conversation context for what was modified
3. Categorize changes by type:

| Change Type | Docs to Update |
|-------------|---------------|
| New feature / UI change | PROJECT_CONTEXT.md, user_guide.md, README.md |
| API / parameter change | PROJECT_CONTEXT.md, developer_guide.md |
| Bug fix | PROJECT_CONTEXT.md (if lesson learned) |
| Refactor | developer_guide.md (if architecture changed) |

### Step 2: Update Documents in Order

Update each document following these specific guidelines:

#### 2.1 Update `context/PROJECT_CONTEXT.md`

This is the AI memory file — **most important**.

- **Version number**: Increment minor version (e.g., v2.8 → v2.9) for feature additions, patch (v2.8.1) for bug fixes
- **Change log**: Add entry to section 8 (变更记录) with:
  - Date
  - Version
  - Summary of changes
  - Files modified
- **Architecture**: Update if code structure changed
- **Lessons learned**: Add to section 9 (经验教训) if a bug revealed new insight
- **API changes**: Update relevant interface definitions

Format for change log entry:
```markdown
### 8.X YYYY-MM-DD 变更标题（vX.Y）

**变更内容：**
- 具体变更1
- 具体变更2

**涉及文件：**
- `path/to/file.py`: 变更说明

**经验教训：**
- 教训描述（如适用）
```

#### 2.2 Update `docs/user_guide.md`

Only update if changes affect **user-facing behavior**:

- New UI elements or interactions
- Changed operation procedures
- New device parameters or modes
- Changed error messages or warnings

Do NOT update for:
- Internal refactoring
- Bug fixes with no user-visible change
- Developer-only API changes

#### 2.3 Update `docs/developer_guide.md`

Only update if changes affect **developer workflows**:

- New API endpoints or parameters
- Changed function signatures
- New validation rules
- Architecture changes
- New development constraints

#### 2.4 Update `README.md`

Only update for:
- New features (update feature table)
- Progress changes (update completion status)
- Changed project structure or setup instructions

### Step 3: Compile Verification

Before committing, verify no syntax errors were introduced:

- `python -m py_compile` for any Python files touched
- No verification needed for .md files

### Step 4: Git Commit

1. Stage all changed documentation files
2. Commit with format: `docs: <brief description>`
3. Show the commit diff to user
4. **Wait for user confirmation before pushing**

### Step 5: Push (After User Confirmation)

Push to both remotes:
```bash
git push origin develop-web
git push github develop-web
```

## Important Rules

- **Never skip PROJECT_CONTEXT.md** — it's the AI memory file
- **Never fabricate changes** — only document what actually changed
- **Never auto-push** — always wait for user confirmation
- **Keep version numbers consistent** across all documents
- **Use Chinese** for all documentation content (matching project convention)
- **Preserve existing document structure** — don't reorganize sections
