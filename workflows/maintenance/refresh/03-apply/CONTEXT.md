---
name: wiki-refresh-apply
description: Apply an accepted refresh proposal through the correct write boundary and verify that retired wording cannot leak into active knowledge.
---

# Stage 03 - Apply

## Inputs

- The accepted, unchanged `tmp/wiki-refresh/<run>/proposal.md`.
- Exact authored drafts and target preimages.
- The user's acceptance and, when required, the exact approval-gate Authorization ID.

## Preflight

Re-read every target. If any preimage changed after proposal drafting, return to Stage 02. Select exactly one path below from the accepted proposal's write boundary.

## Guarded changes

For `analysis-capture`, `artifact-promotion`, or `synthesis-promotion`:

1. Follow the [complete destination staging procedure](../../../../REFERENCES.md#complete-capture-staging). Prepare every authored replacement, registry update, index change, and the refresh log entry below under `tmp/` before application. Follow the applicable boundary workflow and [AGENTS.md](../../../../AGENTS.md#exact-approval-boundary).
2. Use `scripts/stage_capture_proposal.py` to derive backlinks and the final log state. Show the complete generated preview. Apply only after the user approves that unchanged proposal's Authorization ID.
3. After application, run only `python3 scripts/validate_capture_runs.py`, `python3 scripts/wiki_transactions.py status`, and `python3 scripts/lint.py`. Do not invoke the routine finalizer, rebuild backlinks, append the log, or edit durable targets.
4. Write results to `tmp/wiki-refresh/<run>/verification.md`, then report and exit. The routine steps below do not apply.

## Routine changes

For an accepted routine-maintenance proposal:

1. Apply only the reviewed owner-page, enrollment, retired-claim, index, and contradiction changes. Install the replacement owner and enrollment before or together with a retirement entry. Preserve source and historical records.
2. Write `tmp/wiki-refresh/<run>/log-entry.md` using the shape below.
3. Run `python3 scripts/finalize_wiki_update.py --log-entry tmp/wiki-refresh/<run>/log-entry.md`. It rebuilds backlinks, serializes the log entry, and validates the final tree. It refuses pending capture applications.
4. Confirm a successful command exit and matching `passed` result in `finalization.json`. The routine route is retryable maintenance, not an atomic transaction over prior authored edits. Write results and deferred claims to `tmp/wiki-refresh/<run>/verification.md`. Make no further durable edit.

## Log entry

Prepare this entry before either finalization path:

```text
## [YYYY-MM-DD] wiki refresh | <profile and scope>
Owner: <current-state owner>
Claims: current=<ids>; superseded=<ids>; unresolved=<ids>
Retired claim IDs: <ids or none>
Active pages corrected: <paths or none>
Historical occurrences preserved: <paths or none>
Evidence cutoff: <date>
```

## Human Check

Report the final owner, retired claim IDs, active pages corrected, historical occurrences deliberately preserved, verification results, and remaining evidence gaps. Do not describe a partial run as complete.

## Exit

Complete only when the accepted proposal is fully represented in the final tree and the selected final validation passes. If evidence changed during apply, return to assessment rather than improvising a new message.
