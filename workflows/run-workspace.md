# Run workspace

Use this contract for multi-step writes, lint reviews, and reviewed research.
Read-only audits and ordinary chat answers do not create scratch records unless
requested. This contract records progress; each task still owns its review policy.

## Start from a copy

From the repo root, choose a fresh run path under `tmp/`. Never copy over an
existing run. For refresh, retain `tmp/wiki-refresh/<run>/`.

```bash
wiki_run_dir="tmp/<run>"
mkdir -p "$(dirname "$wiki_run_dir")"
test ! -e "$wiki_run_dir" && cp -R workflows/_templates/run "$wiki_run_dir"
```

Fill `request.md` with the request, workflow, exact scope, and inputs.
Fill `status.md` with the next step and unresolved work. Templates and their
uses are listed in [_templates/CONTEXT.md](_templates/CONTEXT.md).
Use one log-entry file per run directory. A new unit of work gets a new directory.

## Record transitions

- Before work, set status to `working` and name the current step.
- After each step, record the last completed step and the output paths.
- When review is required, set `awaiting-review`; record the accepted proposal
  path and the user's acceptance before proceeding. For exact gates, reference
  the Authorization ID and ledger. This record cannot substitute for approval.
- On failure or interruption, retain the files and list the unresolved work.
  Use `blocked` for a known failure, `no-change` or `declined` for those outcomes.
- Set `complete` only after the selected task's required checks pass. Record
  commands, exit codes, and output paths in `verification.md`.

On resumption, inspect `status.md`, the output paths it names, and verification.
Treat missing evidence or a contradiction between records as incomplete work.
Re-read changed target preimages before continuing. Files under `tmp/` are local
and disposable after completion; they are not a durable approval ledger.

## Routine finalization

Write `log-entry.md` only when the task requires a log. The routine finalizer
writes an atomic `finalization.json` alongside that file. It contains the input
entry hash, timestamp, `running`, `failed`, or `passed`, completed steps, and any
error. A retry replaces old success with `running` before doing work. Attempts
in the same run directory are serialized.

`passed` means that invocation completed its checks. It does not verify later
edits, other runs, publication, or every step of the task. A log entry may exist
even when final lint failed. `running` after interruption, `failed`, or a missing
result is not completion. Check the command exit and matching input-entry hash; a stale result cannot override a failed invocation. A path or result-write failure may prevent recording a new result. Save CLI output for the detailed findings.

For paths that do not use routine finalization, including guarded applications,
record the required validation results in `verification.md` and update only
local run status after validation. Never run the finalizer to produce a receipt
for a guarded application.

Existing callers with an entry directly under `tmp/` remain supported, but that directory then holds a single run result. Prefer a fresh directory for each unit of work. Locks serialize finalizer attempts in that directory, not all repository edits. Preserve `.wiki-transactions/` independently of these disposable records.
