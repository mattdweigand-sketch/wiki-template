#!/usr/bin/env python3
"""Deterministic approval gate for capture, promotion, and synthesis.

The gate covers exactly three approval boundaries: filing an analysis
(analysis-capture), applying an artifact promotion (promotion-audit), and
promoting reviewed synthesis output (--kind=synthesis). Unapproved runs are
display-only. Approved reruns append or confirm a structured approval record
before the workflow applies the durable change.

Phases other than `accepted` never cross an approval boundary; the gate takes a
short non-approval path for them (route judgment lives in the routed prose
workflows). Two deterministic guards still apply on that path: no concrete
destination may sit under wiki/analyses/ (placeholders are skipped by design on
this display-only path), and every concrete destination must be under an
allowed durable root.

Determinism: the gate anchors on checkable facts, not only declared flags.
- Any capture route with a wiki/analyses/ destination in its declared scope
  requires --path to the drafted artifact; the gate counts its words itself.
  There is no declared word-count input. The synthesis branch may only touch
  wiki/analyses/ pages that already exist on disk; new analysis pages must go
  through the measured analysis-capture route.
- Approval-required routes reject placeholder ("<...>") paths anywhere in the
  approval scope (primary home and pages touched) and any path outside the
  allowed durable roots, so an approval names real, in-scope files. Before
  writing, every approval record is checked against validate_capture_runs.py's
  own rules; the gate never writes a record its validator would reject.
- synthesis approval displays the reviewed --drafts content and full edit scope
  before durable synthesis changes proceed.

Measurement scope: word_count and draft_sha256 are measured from --path; the
measured file is recorded as word_count_path. synthesized_pages is a declared
value, never measured; validate_capture_runs.py re-checks that declared number
for the 3-page analysis qualification.

Exit codes:
  0: approved route is allowed to proceed
  2: approval required before proceeding
  3: invalid or blocked route (argparse usage errors are remapped here so that
     exit 2 always means exactly "approval required")
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from _repo_paths import RepoPathError
from _wiki_parse import FrontmatterError, canonical_authored_text
from capture_approval_policy import (
    ACTION_LABELS,
    ANALYSES_PREFIX,
    APPROVAL_ROUTES,
    DraftSha256,
    PROMOTION_TRIGGERS,
    approval_guard,
    classify_accepted,
    contains_approval_path_placeholder,
    is_analyses_path,
    measure_draft,
    normalize_path,
    real_destinations,
    scope_with_home,
)
from capture_approval_records import (
    AuthoredSha256,
    DEFAULT_APPROVAL_LEDGER,
    LEDGER_SCHEMA_DESCRIPTION,
    SYNTHESIS_DEFAULT_HOME,
    append_capture_approval_record,
    capture_approval_record,
    synthesis_approval_record,
)
from ledger_common import LedgerIntegrityError, split_scope
from validate_capture_runs import validate_approval


FREE_PHASES = ("drafting", "source", "decision", "experience", "workflow")


def yn(value: str) -> bool:
    lowered = value.lower()
    if lowered in {"yes", "true", "1", "y"}:
        return True
    if lowered in {"no", "false", "0", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected yes/no")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Require approval for wiki analysis capture, promotion, or synthesis.",
    )
    p.add_argument("--artifact", required=True, help="Short description of the artifact.")
    p.add_argument(
        "--kind",
        choices=["capture", "synthesis"],
        default="capture",
        help="Approval branch. Default capture preserves existing phase-derived behavior.",
    )
    p.add_argument(
        "--phase",
        choices=["accepted", *FREE_PHASES],
        help="Current state of the user request. Required for --kind=capture. Only "
             "'accepted' can derive an approval route; every other phase takes the "
             "short non-approval path.",
    )
    p.add_argument("--primary-home", default="", help="Exact intended path, if known.")
    p.add_argument("--pages-touched", default="", help="Comma-separated intended paths.")
    p.add_argument("--source-path", default="", help="Source path or URL if a source is involved.")
    p.add_argument(
        "--path",
        default="",
        help="Path to the drafted artifact on disk. Required whenever the primary "
             "home is under wiki/analyses/; the gate counts its words itself.",
    )
    p.add_argument("--drafts", default="", help="Reviewed synthesis content for --kind=synthesis.")
    p.add_argument("--synthesized-pages", type=int, default=0)
    p.add_argument(
        "--domain-context",
        dest="domain_context",
        type=yn,
        default=False,
        help="Whether the answer is about this wiki's configured domain.",
    )
    p.add_argument(
        "--trigger",
        action="append",
        choices=PROMOTION_TRIGGERS,
        default=[],
        help="Reusable-artifact trigger. Repeat for multiple triggers.",
    )
    p.add_argument(
        "--approved",
        action="store_true",
        help="Set only after the user explicitly approves this exact route.",
    )
    p.add_argument(
        "--approval-ledger",
        default=DEFAULT_APPROVAL_LEDGER,
        help="JSONL file for approved capture, promotion, and synthesis records.",
    )
    return p




def print_capture_summary(args: argparse.Namespace, route: str, home: str, reason: str,
                          scope: list[str]) -> None:
    files = ", ".join(scope) if scope else (home if home else "none")
    print("CAPTURE GATE")
    print(f"Artifact: {args.artifact}")
    print(f"Machine mode: {route}")
    if route in ACTION_LABELS:
        print(f"Proposed action: {ACTION_LABELS[route]}")
    print(f"Primary home: {home}")
    print(f"Reason: {reason}")
    print(f"Pages touched: {files}")


def print_synthesis_summary(args: argparse.Namespace, home: str, scope: list[str]) -> None:
    print("CAPTURE GATE")
    print(f"Artifact: {args.artifact}")
    print("Machine mode: synthesis")
    print("Proposed action: Approve synthesis content and update the synthesis ledger.")
    print(f"Primary home: {home}")
    print(f"Drafts for review: {args.drafts}")
    print(f"Files the agent may edit after approval: {', '.join(scope)}")


def print_capture_approval_request(args: argparse.Namespace, route: str, home: str,
                                   scope: list[str]) -> None:
    action = ACTION_LABELS[route]
    files = ", ".join(scope)
    print()
    print("APPROVAL REQUIRED")
    print("No files have been changed yet.")
    print()
    print("What you are approving:")
    print(f"- Durable action: {action}")
    print(f"- Artifact: {args.artifact}")
    print(f"- Primary destination: {home}")
    print(f"- Files the agent may edit: {files}")
    print()
    print("Approve only if these are correct:")
    print("- This artifact should be saved to the wiki, not left in chat.")
    print("- The primary destination is the right durable home.")
    print("- The file list is the full intended edit scope.")
    print()
    print('Reply with plain-language approval, such as "approve" or "yes", or say what should change.')
    print()
    print("Agents: re-run with --approved only after the user clearly approves the displayed action, destination, and file scope.")


def print_synthesis_approval_request() -> None:
    print()
    print("APPROVAL REQUIRED")
    print("Do not update wiki/synthesis.md, flip draft confidence/status, or log a synthesis promotion yet.")
    print()
    print("Approve only if these are correct:")
    print("- The reviewed synthesis content is right.")
    print("- The primary ledger/durable home is right.")
    print("- The file list is the full intended approval edit scope.")
    print()
    print('Reply with plain-language approval, such as "approve" or "yes", or say what should change.')
    print()
    print("Agents: re-run with --approved only after the user clearly approves the displayed draft and file scope.")


def print_capture_approval_confirmed(args: argparse.Namespace, route: str, home: str,
                                     scope: list[str]) -> None:
    print()
    print("APPROVAL CONFIRMED")
    print(f"Approved action: {ACTION_LABELS[route]}")
    print(f"Approved primary destination: {home}")
    print(f"Approved file scope: {', '.join(scope)}")
    print(f"Approval record: {args.approval_ledger}")
    print("Proceed only within this approved scope.")


def print_synthesis_approval_confirmed(args: argparse.Namespace, home: str, scope: list[str]) -> None:
    print()
    print("APPROVAL CONFIRMED")
    print(f"Approved synthesis: {args.artifact}")
    print(f"Approved primary home: {home}")
    print(f"Approved file scope: {', '.join(scope)}")
    print(f"Approval record: {args.approval_ledger}")
    print("Proceed only within this approved scope.")


def blocked(reason: str, args: argparse.Namespace) -> int:
    """Print the BLOCKED banner with the reason and return exit code 3."""
    print("CAPTURE GATE: BLOCKED")
    print(f"Artifact: {args.artifact}")
    print(f"Reason: {reason}")
    return 3


def synthesis_guard(args: argparse.Namespace, home: str, scope: list[str]) -> str | None:
    if not args.artifact.strip():
        return ("--artifact must be a non-empty description; the gate will not "
                "write an approval record its own validator would reject.")
    if not args.drafts.strip():
        return "Synthesis approval requires --drafts so the user can review what changed."
    if not args.pages_touched.strip():
        return "Synthesis approval requires --pages-touched so the editable scope is explicit."

    checked_scope = scope + [home]
    placeholders = [p for p in checked_scope if p and contains_approval_path_placeholder(p)]
    if placeholders:
        return f"approval scope must name concrete paths, not placeholders: {placeholders}"
    if home not in scope:
        return f"primary home {home} must be included in --pages-touched."
    # Synthesis flips status on existing, already-reviewed analyses pages. A
    # NEW analysis has a draft to measure, so it must go through the measured
    # analysis-capture route instead of this unmeasured branch.
    missing_analyses = [p for p in checked_scope
                        if p and is_analyses_path(p) and not Path(p).is_file()]
    if missing_analyses:
        return (f"synthesis may only touch existing {ANALYSES_PREFIX} pages; file a "
                f"new analysis through analysis-capture with a measured draft: "
                f"missing {missing_analyses}")
    return None


def run_synthesis(args: argparse.Namespace) -> int:
    home = args.primary_home.strip() or SYNTHESIS_DEFAULT_HOME
    if home and not contains_approval_path_placeholder(home):
        home = normalize_path(home)
    scope = list(dict.fromkeys(normalize_path(p) for p in split_scope(args.pages_touched)))

    reason = synthesis_guard(args, home, scope)
    if reason:
        return blocked(reason, args)

    print_synthesis_summary(args, home, scope)
    if args.approved:
        record = synthesis_approval_record(args, home, scope)
        problems = validate_approval(record)
        if problems:
            return blocked("refusing to write an approval record its own validator "
                           "rejects: " + "; ".join(problems), args)
        wrote, ledger_path, label, record_hash = append_capture_approval_record(
            record, args.approval_ledger, "synthesis_approval"
        )
        print("Approval: confirmed for this exact synthesis content and file scope.")
        if wrote:
            print(f"Structured approval record: appended approval for {label} to {ledger_path}")
        else:
            print(f"Structured approval record: already present for {label} in {ledger_path}")
        print(f"Approval record SHA-256: {record_hash}")
        print_synthesis_approval_confirmed(args, home, scope)
        return 0

    print_synthesis_approval_request()
    return 2


def run_free_phase(args: argparse.Namespace) -> int:
    """Phases other than accepted never require this gate; the routed prose
    workflows own that judgment. Two deterministic guards still apply so a
    mistaken invocation cannot legitimize a bad destination."""
    home = args.primary_home.strip()
    if home and home != "none" and not contains_approval_path_placeholder(home):
        home = normalize_path(home)

    if any(is_analyses_path(d) for d in real_destinations(home, args.pages_touched)):
        return blocked(f"phase '{args.phase}' may not write to {ANALYSES_PREFIX}; "
                       "an analysis must go through analysis-capture or promotion-audit.",
                       args)

    print("CAPTURE GATE")
    print(f"Artifact: {args.artifact}")
    print(f"Machine mode: non-approval (phase {args.phase})")
    print("Approval: not required; only --phase accepted can cross an approval "
          "boundary. Route judgment lives in the routed workflows; do not edit "
          "files a drafting conversation has not asked for.")
    return 0


def run_capture(args: argparse.Namespace) -> int:
    if not args.phase:
        return blocked("--phase is required when --kind=capture.", args)

    if args.phase != "accepted":
        return run_free_phase(args)

    # Measure the word count from the real draft when a path is given, so the
    # decision rests on a fact rather than a declared number. An unreadable
    # --path blocks here with the precise diagnosis; letting it fall through
    # would misclassify the run as chat-only and report the wrong problem.
    word_count = 0
    word_count_source = "unmeasured"
    draft_sha256: DraftSha256 | None = None
    draft_text = ""
    if args.path:
        measured = measure_draft(args.path)
        if measured is None:
            return blocked(f"--path {args.path!r} is not a readable file.", args)
        word_count, draft_sha256, draft_text = measured
        word_count_source = "measured"

    if args.synthesized_pages < 0:
        return blocked("--synthesized-pages must be a non-negative count of "
                       "distinct wiki pages synthesized.", args)

    route, home, reason = classify_accepted(args, word_count)
    # Normalize a concrete home once so every downstream check and stored record
    # see the same resolved path.
    if home and home != "none" and not contains_approval_path_placeholder(home):
        home = normalize_path(home)

    # These guards check the DECLARED inputs, not the route-derived home: a
    # chat-only classification discards --primary-home, and a discarded
    # analyses or out-of-root declaration must still block rather than exit 0.
    declared_home = args.primary_home.strip()
    if route not in APPROVAL_ROUTES:
        analyses_declared = [d for d in real_destinations(declared_home, args.pages_touched)
                             if is_analyses_path(d)]
        if analyses_declared:
            hint = ""
            if not args.path:
                hint = (" If this is a drafted analysis, re-run with --path to the "
                        "draft so its word count is measured, not declared.")
            return blocked(f"route '{route}' may not write to {ANALYSES_PREFIX}; "
                           "an analysis must go through analysis-capture or "
                           f"promotion-audit.{hint}", args)

    approval_required = route in APPROVAL_ROUTES

    if approval_required:
        block = approval_guard(args, route, home)
        if block:
            return blocked(block, args)

    scope = scope_with_home(home, args.pages_touched)
    authored_sha256: AuthoredSha256 | None = None
    if args.path and (
        route == "analysis-capture" or any(is_analyses_path(path) for path in scope)
    ):
        try:
            authored = canonical_authored_text(draft_text).encode("utf-8")
        except FrontmatterError as exc:
            return blocked(
                f"--path {args.path!r} has malformed frontmatter: {exc}", args
            )
        authored_sha256 = AuthoredSha256(hashlib.sha256(authored).hexdigest())
    print_capture_summary(args, route, home, reason, scope)

    if route == "chat-only":
        print("Approval: not required; do not edit files.")
        return 0

    if args.approved:
        record = capture_approval_record(args, route, home, scope,
                                         word_count, word_count_source,
                                         draft_sha256, authored_sha256)
        problems = validate_approval(record)
        if problems:
            return blocked("refusing to write an approval record its own validator "
                           "rejects: " + "; ".join(problems), args)
        wrote, ledger_path, label, record_hash = append_capture_approval_record(
            record, args.approval_ledger, "capture_approval"
        )
        print("Approval: confirmed for this exact route.")
        if wrote:
            print(f"Structured approval record: appended approval for {label} to {ledger_path}")
        else:
            print(f"Structured approval record: already present for {label} in {ledger_path}")
        print(f"Approval record SHA-256: {record_hash}")
        print_capture_approval_confirmed(args, route, home, scope)
        return 0

    print_capture_approval_request(args, route, home, scope)
    return 2


def main() -> int:
    try:
        args = parser().parse_args()
    except SystemExit as exc:
        # argparse exits 2 on usage errors, which would collide with this
        # gate's "approval required" code; remap so exit 2 keeps one meaning.
        if exc.code == 2:
            return 3
        return exc.code if isinstance(exc.code, int) else 3
    args.trigger = sorted(set(args.trigger))
    try:
        if args.kind == "synthesis":
            return run_synthesis(args)
        return run_capture(args)
    except (RepoPathError, LedgerIntegrityError) as exc:
        return blocked(str(exc), args)


if __name__ == "__main__":
    sys.exit(main())
