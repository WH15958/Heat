---
name: "code-review"
description: "Reviews code against Heat project rules. Invoke after code modifications, before commits, or when user asks for code review."
---

# Code Review for Heat Project

Review code changes against Heat project development rules. This skill enforces the self-check checklist defined in heat.md section 9.2.

## When to Invoke

- After any code modification (Python or TypeScript/Vue)
- Before Git commits
- When user asks for code review
- When user types `/review`

## Review Process

### Step 1: Identify Changed Files

Use `git diff --name-only` or read the files that were just modified in the current conversation.

### Step 2: Execute Checklist

For each changed file, check the following items:

#### Python Files Checklist

| # | Check Item | Rule Source | Pass Criteria |
|---|-----------|-------------|---------------|
| 1 | Serial port threading | 2.1 | No threads created inside `src/devices/` |
| 2 | Lock protection | 5.1/5.2 | All serial access protected by `RLock`, lock scope minimized |
| 3 | Device safety | 4.2 | Write ops check connection, return values checked |
| 4 | Parameter validation | 4.4 | Numeric type/range/default values complete |
| 5 | Resource cleanup | 5.1 | `try...finally` covers all exception paths |
| 6 | No daemon threads | 5.1 | No `daemon=True` threads |
| 7 | No bare while True | 5.1 | All loops check `stop_event.is_set()` |
| 8 | No long sleep | 5.1 | Long sleeps split into short intervals |
| 9 | Protocol stateless | 2.2 | Protocol classes don't cache data or maintain state |
| 10 | run_in_executor | 2.3 | No direct device calls in async functions |
| 11 | Common pitfalls | 5.3 | `x or default` → `x if x is not None else default`; enum safety; deepcopy; retry_count ≥ 1 |
| 12 | Code style | 3.1 | snake_case, type annotations, no comments, line ≤ 100 chars |

#### TypeScript/Vue Files Checklist

| # | Check Item | Rule Source | Pass Criteria |
|---|-----------|-------------|---------------|
| 1 | Component cleanup | 3.2 | `onUnmounted` closes WebSocket, timers, popups |
| 2 | ECharts usage | 7.2 | `replaceMerge` for setOption, `ResizeObserver`, try-catch on init, dynamic units |
| 3 | Element Plus | 7.3 | `:loading` on delete, `ElMessageBox.confirm`, precision/step match |
| 4 | Data flow | 7.1 | Real-time via WebSocket, operations via REST API, params persisted to localStorage |
| 5 | Code style | 3.2 | camelCase/PascalCase naming, Composition API, `<script setup lang="ts">` |

### Step 3: Compile Verification

Run the appropriate compile check:

- Python: `python -m py_compile <file>`
- Frontend: `cd frontend && npx vue-tsc --noEmit`

### Step 4: Output Report

Format the review report as:

```
## Code Review Report

**Files Reviewed**: <file list>

### Checklist Results

| # | Check Item | Result | Details |
|---|-----------|--------|---------|
| 1 | Serial port threading | ✅/❌ | <details if failed> |
| ... | ... | ... | ... |

### Compile Verification
- <file>: ✅ passed / ❌ <error>

### Summary
- **Result**: PASS / FAIL
- **Issues Found**: <count>
- **Critical Issues**: <count>
```

### Verdict Rules

- **PASS**: All checklist items pass + compile verification passes
- **FAIL**: Any critical item fails (items 1-5 for Python, items 1-2 for Vue) OR compile fails
- On FAIL: Fix the issues and re-run the review

## Important Notes

- This is a self-check by the same AI that wrote the code — be extra strict
- When in doubt, mark as FAIL rather than PASS
- Critical items (serial safety, lock, device safety) are non-negotiable
- Always run compile verification — it's the only objective check
