# AGENTS.md

Codex project instructions for Heat.

Heat is a lab automation and experiment-control system. Treat it as a hardware-adjacent control project, not as a generic web app. Be conservative, verify behavior, and keep device safety and experiment traceability ahead of convenience.

## 1. Ground Truth

- Read `context/PROJECT_CONTEXT.md` before non-trivial code changes.
- Use current code as the source of truth when docs and implementation disagree.
- Check these docs when the change touches their area:
  - `docs/user_guide.md`: user-facing operation and behavior.
  - `docs/developer_guide.md`: architecture, APIs, and maintenance.
  - `docs/experiment_yaml_spec.md`: YAML schema and examples.
  - `docs/testing_and_merge_flow.md`: validation, commit, merge, and push workflow.
  - `docs/campaign_workflow.md`: human-in-the-loop optimization workflow.

## 2. Heat Safety Rules

- Do not rewrite synchronous device drivers into async/threaded drivers.
- Do not add polling, heartbeats, or command queues inside `src/devices/`.
- Device calls should remain synchronous; async bridging belongs in the Web or orchestration layer.
- Do not bypass existing serial/resource management.
- Do not let WebSocket connect/disconnect events start, stop, or otherwise control hardware.
- Treat device return values seriously. A `False` return or timeout must not be logged as success.
- Preserve stop/pause/resume semantics and make long waits interruptible.
- Planner or ML code may recommend parameters, but must not directly control hardware.
- Hardware timing, protocol writes, serial resource behavior, and real start/stop behavior require human/lab confirmation or real-device smoke testing.

## 3. Change Discipline

- Make the smallest change that solves the request.
- Do not refactor adjacent code unless the task requires it.
- Match the existing style even when it is not your preferred style.
- Do not invent unsupported actions, wait types, routes, device capabilities, or chemistry recipes.
- Keep generated/runtime data out of commits unless the project already tracks that exact artifact intentionally.
- Remove only unused code created by your own change. Mention unrelated dead code instead of deleting it.

## 4. PowerShell Performance Strategy

This workspace can stall on broad PowerShell output. Prefer narrow, low-output commands.

- Use `rg` or `rg --files` for search.
- Prefer path-scoped git commands such as `git status --short -- <paths>` and `git diff -- <paths>`.
- For large reads or noisy git output, use Node `spawnSync` or targeted file reads instead of broad PowerShell pipelines.
- Avoid defaulting to recursive `Get-ChildItem`, large `Format-Table` output, unscoped `git status`, or huge diffs through PowerShell.
- When checking generated frontend declarations, inspect content diff and EOL state before deciding whether to stage.

## 5. Documentation Mapping

Update docs only when the change affects that document's area.

| Change type | Documents |
| --- | --- |
| New page, button, user operation, or visible behavior | `docs/user_guide.md` |
| API path, request/response shape, backend architecture, or developer workflow | `docs/developer_guide.md` |
| YAML action, wait type, metadata field, or experiment file format | `docs/experiment_yaml_spec.md` |
| `sample_id`, `samples.csv`, campaign, trial, recommendation, or characterization flow | `docs/campaign_workflow.md`; also `docs/user_guide.md` if user-facing |
| Validation, branch, commit, merge, push, or `/git` workflow | `docs/testing_and_merge_flow.md` |
| Project positioning, major capability list, setup, or top-level usage | `README.md` |
| Long-lived AI/project facts, hardware boundaries, or agent rules | `context/PROJECT_CONTEXT.md` and/or `AGENTS.md` |
| Internal implementation only, no interface or behavior change | Usually no user docs; update `docs/developer_guide.md` only if architecture changed |
| Agent/rule/skill-only changes | No full build required; do document consistency and git checks |

If an existing long Chinese document displays with mojibake in the terminal, avoid rewriting it wholesale. Prefer targeted edits or add a focused new doc.

## 6. Validation Matrix

Run the narrowest checks that match the change. Do not run expensive builds for docs-only or rule-only edits unless the docs describe build/runtime behavior that needs verification.

| Change type | Default checks |
| --- | --- |
| Docs, rules, or skill-only | `git diff --check -- <paths>` plus targeted content review |
| Python backend | `python tests\test_metadata.py` and relevant import checks |
| Campaign / planner | Backend checks plus `python -c "import src.web.api.campaigns; import src.campaigns.store; import src.ml.planner"` |
| Frontend source | `cd frontend; npm run build -- --mode production` |
| YAML parser or experiment engine | Metadata tests plus targeted import or behavior checks |
| Hardware-facing behavior | Software checks plus explicit user/lab smoke-test confirmation |

Common backend import check:

```powershell
python -c "import src.web.app; import src.web.api.experiments; import src.web.api.ws"
```

If `pytest` is installed, run targeted pytest files such as:

```powershell
python -m pytest tests\test_campaigns.py -q
```

If `pytest` is not installed, say so and use an equivalent targeted Python validation when practical.

## 7. Git Workflow

Use task branches for normal development. Do not start routine work directly on `master`.

Before committing:

1. Inspect the worktree with targeted `git status --short` and relevant diffs.
2. Distinguish real source changes from generated files and line-ending churn.
3. Choose validation from the validation matrix.
4. Update only the documents required by the documentation mapping.
5. Stage only relevant files.
6. Run `git diff --cached --check`.
7. Commit with a concise message.

Recommended commit prefixes:

- `feat:`
- `fix:`
- `docs:`
- `refactor:`
- `test:`

Do not push unless the user explicitly confirms.

When the user says `/git`, interpret it as:

```text
validate as needed -> update docs as needed -> commit -> wait for user confirmation before push
```

`/git` does not mean:

```text
push automatically
reset unrelated files
clean untracked files
overwrite user changes
run every build for docs-only changes
```

If pushing after user confirmation, push the current branch to both configured remotes when available:

```powershell
git push origin <branch>
git push github <branch>
```

## 8. Generated Files

- `frontend/auto-imports.d.ts` is generated by `unplugin-auto-import`.
- `frontend/components.d.ts` is generated by `unplugin-vue-components`.
- These files may change after frontend builds.
- Check content diffs before deciding whether to commit them.
- Do not delete or revert generated declaration files blindly.

## 9. Human-in-the-loop Optimization Boundary

The current intelligent-experiment direction is batch, human-in-the-loop optimization:

- Heat records campaigns, trials, recommendations, samples, and offline characterization results.
- `ManualPlanner` is the default planner.
- Future ML planners should reuse the planner interface and Campaign history.
- Offline characterization is manually entered in v1.
- Trial parameters are not automatically injected into YAML in v1.
- Experiment execution remains explicit and human-supervised through the existing experiment workflow.
- The user/lab decides whether a characterization result is scientifically valid for planner feedback.

## 10. Responsibility Split

Codex can:

- modify software
- add tests
- update docs
- prepare templates and checklists
- validate imports/builds
- reason about architecture and data flow

The user/lab must confirm:

- actual device identity and wiring
- safety authorization
- SOP changes
- reagent compatibility
- real hardware behavior
- vendor/procurement decisions
- scientific validity of planner feedback
