#!/usr/bin/env python3
"""Regression eval for flat route diagnosis and exact proposal requirements."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_lib import Results
from validate_capture_runs import validate_approval

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "capture_gate.py"
SYNTHESIZE_WORKFLOW = REPO_ROOT / "workflows" / "maintenance" / "synthesize.md"
TMP = tempfile.TemporaryDirectory()
LIVE_APPROVAL_LEDGER = REPO_ROOT / "scripts" / "capture-runs.jsonl"
LIVE_APPROVAL_LEDGER_PREIMAGE = LIVE_APPROVAL_LEDGER.read_bytes()
DRAFT = Path(TMP.name) / "draft.md"
DRAFT.write_text("word " * 350)  # >300 measured words so the analysis bar is met
SHORT_DRAFT = Path(TMP.name) / "short-draft.md"
SHORT_DRAFT.write_text("word " * 50)  # 50 measured words, below the 300-word bar
DRAFT_300 = Path(TMP.name) / "draft-300.md"
DRAFT_300.write_text("word " * 300)
DRAFT_301 = Path(TMP.name) / "draft-301.md"
DRAFT_301.write_text("word " * 301)
MALFORMED_FRONTMATTER_DRAFT = Path(TMP.name) / "malformed-frontmatter-draft.md"
MALFORMED_FRONTMATTER_DRAFT.write_text(
    "---\ntitle: malformed\n---junk\n" + "word " * 50
)
# Sandbox repo root for existence-sensitive cases: the synthesis branch checks
# analyses paths against the invocation cwd, so these cases run inside here.
SANDBOX = Path(TMP.name) / "sandbox-repo"
(SANDBOX / "wiki" / "analyses").mkdir(parents=True)
(SANDBOX / "wiki" / "analyses" / "existing-eval.md").write_text("existing analysis page\n")
OUTSIDE_SCOPE = Path(TMP.name) / "outside-scope"
OUTSIDE_SCOPE.mkdir()
(SANDBOX / "wiki" / "escape").symlink_to(OUTSIDE_SCOPE, target_is_directory=True)

results = Results()

def run_case(name, args, expect_code, expect=(), absent=(), cwd=None):
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--artifact",
            "eval fixture",
            *args,
        ],
        text=True, capture_output=True, cwd=cwd,
    )
    ok = proc.returncode == expect_code
    for marker in expect:
        ok = ok and marker in proc.stdout
    for marker in absent:
        ok = ok and marker not in proc.stdout
    detail = (
        f"exit {proc.returncode} (expected {expect_code}); stdout: "
        + proc.stdout.replace("\n", " | ")
        + "; stderr: "
        + proc.stderr.replace("\n", " | ")
    )
    results.record(name, ok, detail)


ANALYSIS = ["--phase", "accepted", "--synthesized-pages", "3", "--domain-context", "yes",
            "--primary-home", "wiki/analyses/eval.md",
            "--pages-touched", "wiki/analyses/eval.md,wiki/log.md",
            "--path", str(DRAFT)]

PROMO = ["--phase", "accepted", "--trigger", "reusable_distinction",
         "--primary-home", "wiki/concepts/foo.md", "--pages-touched", "wiki/concepts/foo.md"]

SYNTHESIS = [
    "--kind", "synthesis",
    "--drafts", "wiki/primer.md local-AI routing row",
    "--pages-touched", "wiki/primer.md,wiki/synthesis.md,wiki/log.md",
]


def check_live_ledger_unchanged(name: str) -> None:
    current = LIVE_APPROVAL_LEDGER.read_bytes()
    results.record(
        name,
        current == LIVE_APPROVAL_LEDGER_PREIMAGE,
        "live approval ledger changed" if current != LIVE_APPROVAL_LEDGER_PREIMAGE else "",
    )

def capture_record_fixture(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "record_type": "capture_approval",
        "schema_version": 1,
        "approval_status": "approved",
        "approved_at": "2026-07-08T17:11:14Z",
        "artifact": "eval fixture",
        "route": "analysis-capture",
        "phase": "accepted",
        "primary_home": "wiki/analyses/eval.md",
        "pages_touched": ["wiki/analyses/eval.md", "wiki/log.md"],
        "source_path": "",
        "synthesized_pages": 3,
        "word_count": 350,
        "word_count_source": "measured",
        "word_count_path": str(DRAFT),
        "domain_context": True,
        "triggers": [],
    }
    record.update(updates)
    return record








def check_validator_draft_hash_rules() -> None:
    missing_errors = validate_approval(capture_record_fixture())
    malformed_errors = validate_approval(capture_record_fixture(
        approved_at="2026-07-08T17:11:13Z",
        draft_sha256="ABC",
    ))
    pre_cutoff_errors = validate_approval(capture_record_fixture(
        approved_at="2026-07-08T17:11:13Z",
    ))
    post_cutoff_unmeasured_errors = validate_approval(capture_record_fixture(
        route="promotion-audit",
        primary_home="wiki/concepts/foo.md",
        pages_touched=["wiki/concepts/foo.md"],
        synthesized_pages=0,
        word_count=0,
        word_count_source="unmeasured",
        word_count_path="",
        domain_context=False,
        triggers=["existing_page_update"],
    ))
    ok = (
        any("draft_sha256" in error for error in missing_errors)
        and any("draft_sha256" in error for error in malformed_errors)
        and pre_cutoff_errors == []
        and post_cutoff_unmeasured_errors == []
    )
    detail = (
        f"missing: {missing_errors!r}; malformed: {malformed_errors!r}; "
        f"pre_cutoff: {pre_cutoff_errors!r}; "
        f"post_cutoff_unmeasured: {post_cutoff_unmeasured_errors!r}"
    )
    results.record("capture-validator-enforces-commissioned-draft-sha", ok, detail)










SHELL_FENCE_RE = re.compile(
    r"^[ \t]*```(?:bash|sh|shell)[ \t]*\n(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


def fenced_shell_commands(text: str) -> tuple[list[list[str]], list[str]]:
    """Parse executable-looking commands only from fenced shell blocks."""
    commands: list[list[str]] = []
    problems: list[str] = []
    for block in SHELL_FENCE_RE.finditer(text):
        pending = ""
        for raw_line in block.group("body").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("\\"):
                pending += line[:-1].rstrip() + " "
                continue
            logical = (pending + line).strip()
            pending = ""
            try:
                commands.append(shlex.split(logical))
            except ValueError as exc:
                problems.append(f"unparseable fenced shell command {logical!r}: {exc}")
        if pending:
            problems.append("fenced shell command ends with a dangling continuation")
    return commands, problems


def invoked_script(command: list[str]) -> str | None:
    """Return a directly executed script or Python's argv[1] script."""
    if not command:
        return None
    first = command[0].removeprefix("./")
    if first.startswith("scripts/") and first.endswith(".py"):
        return first
    interpreter = Path(command[0]).name
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", interpreter) and len(command) > 1:
        candidate = command[1].removeprefix("./")
        if candidate.startswith("scripts/") and candidate.endswith(".py"):
            return candidate
    return None


def flag_value(command: list[str], flag: str) -> str | None:
    for index, token in enumerate(command):
        if token == flag:
            value = command[index + 1] if index + 1 < len(command) else None
            return value if value and not value.startswith("-") else None
        if token.startswith(flag + "="):
            value = token.split("=", 1)[1]
            return value if value and not value.startswith("-") else None
    return None


def synthesis_workflow_problems(text: str) -> list[str]:
    commands, problems = fenced_shell_commands(text)
    if "capture_boundary: synthesis-promotion" not in text:
        problems.append("missing capture_boundary: synthesis-promotion contract")

    section_start = text.find("2. For synthesis promotion")
    section_end = text.find("\n3. ", section_start)
    synthesis_section = (
        text[section_start:section_end]
        if section_start >= 0 and section_end > section_start
        else ""
    )
    synthesis_commands, section_problems = fenced_shell_commands(synthesis_section)
    problems.extend(section_problems)
    synthesis_gates = [
        command
        for command in synthesis_commands
        if invoked_script(command) == "scripts/capture_gate.py"
    ]
    preview_gates = [
        command
        for command in synthesis_gates
        if flag_value(command, "--proposal") and "--approve-digest" not in command
    ]
    apply_gates = [
        command
        for command in synthesis_gates
        if flag_value(command, "--proposal") and "--approve-digest" in command
    ]
    if not preview_gates:
        problems.append("missing fenced synthesis proposal preview command")
    if not apply_gates:
        problems.append("missing fenced synthesis proposal apply command")
    else:
        apply_gate = apply_gates[0]
        if not flag_value(apply_gate, "--approve-digest"):
            problems.append("synthesis apply command missing value for --approve-digest")

    if not any(
        invoked_script(command) == "scripts/validate_capture_runs.py"
        for command in commands
    ):
        problems.append("missing fenced validate_capture_runs.py command")
    if not any(
        invoked_script(command) == "scripts/rebuild_referenced_by.py"
        for command in commands
    ):
        problems.append("missing fenced rebuild_referenced_by.py command")
    if not any(
        invoked_script(command) == "scripts/lint.py" and "--tier1" in command
        for command in commands
    ):
        problems.append("missing fenced lint.py --tier1 command")
    return problems


def check_workflow_contract() -> None:
    text = SYNTHESIZE_WORKFLOW.read_text(encoding="utf-8")
    problems = synthesis_workflow_problems(text)
    results.record(
        "synthesize-workflow-requires-gate",
        not problems,
        "problems: " + "; ".join(problems),
    )

    fixtures = (
        (
            "synthesize-workflow-rejects-wrong-kind",
            text.replace(
                "capture_boundary: synthesis-promotion",
                "capture_boundary: artifact-promotion",
                1,
            ),
            "synthesis-promotion",
        ),
        (
            "synthesize-workflow-rejects-missing-drafts",
            text.replace(
                "python3 scripts/capture_gate.py --proposal tmp/<proposal>.json --json\n"
                "   # After approval",
                "python3 scripts/capture_gate.py --descriptor tmp/<proposal>.json --json\n"
                "   # After approval",
                1,
            ),
            "proposal preview",
        ),
        (
            "synthesize-workflow-rejects-prose-only-validator",
            text.replace(
                "python3 scripts/validate_capture_runs.py",
                "echo validation-complete",
                1,
            ) + "\nProse mentions scripts/validate_capture_runs.py.\n",
            "validate_capture_runs.py",
        ),
        (
            "synthesize-workflow-rejects-wrong-lint-flag",
            text.replace("scripts/lint.py --tier1", "scripts/lint.py --tier2", 1),
            "lint.py --tier1",
        ),
        (
            "synthesize-workflow-rejects-echo-gate-decoy",
            text.replace(
                "python3 scripts/capture_gate.py --proposal tmp/<proposal>.json --json\n"
                "   # After approval",
                "echo scripts/capture_gate.py --proposal tmp/<proposal>.json --json\n"
                "   # After approval",
                1,
            ),
            "proposal preview",
        ),
        (
            "synthesize-workflow-rejects-valueless-artifact",
            text.replace(
                "--approve-digest <authorization_digest> --json",
                "--approve-digest --json",
                1,
            ),
            "missing value for --approve-digest",
        ),
        (
            "synthesize-workflow-rejects-echo-validator-decoy",
            text.replace(
                "python3 scripts/validate_capture_runs.py",
                "echo scripts/validate_capture_runs.py",
                1,
            ),
            "validate_capture_runs.py",
        ),
        (
            "synthesize-workflow-rejects-echo-rebuild-decoy",
            text.replace(
                "python3 scripts/rebuild_referenced_by.py",
                "echo scripts/rebuild_referenced_by.py",
                1,
            ),
            "rebuild_referenced_by.py",
        ),
        (
            "synthesize-workflow-rejects-echo-lint-decoy",
            text.replace(
                "python3 scripts/lint.py --tier1",
                "echo scripts/lint.py --tier1",
                1,
            ),
            "lint.py --tier1",
        ),
    )
    for name, fixture, marker in fixtures:
        fixture_problems = synthesis_workflow_problems(fixture)
        results.record(
            name,
            any(marker in problem for problem in fixture_problems),
            f"expected {marker!r}; problems: {fixture_problems!r}",
        )


# Flat mode diagnoses routes but cannot approve durable application.
run_case("analysis-requires-approval", ANALYSIS, 2,
         expect=("analysis-capture", "APPROVAL REQUIRED",
                 "What you are approving:",
                 'Reply with plain-language approval'),
         absent=("Reply exactly:",))
check_live_ledger_unchanged("unapproved-analysis-does-not-write-structured-record")
run_case(
    "legacy-approved-is-rejected",
    ANALYSIS + ["--approved"],
    3,
    expect=("legacy --approved is disabled", "--proposal"),
    absent=("Approval: confirmed", "APPROVAL CONFIRMED"),
)
check_live_ledger_unchanged("legacy-approved-writes-no-record")
check_validator_draft_hash_rules()
run_case("promotion-requires-approval", PROMO, 2,
         expect=("promotion-audit", "APPROVAL REQUIRED",
                 "Durable action: Apply an artifact promotion to the wiki.",
                 "reusable distinction"))

# Free phases: never require this gate; route judgment lives in the prose
# workflows, so the gate prints a short non-approval notice and exits 0.
for free_phase in ("drafting", "source", "decision", "experience", "workflow"):
    run_case(f"{free_phase}-phase-never-requires-approval", ["--phase", free_phase], 0,
             expect=(f"non-approval (phase {free_phase})", "not required"),
             absent=("APPROVAL REQUIRED",))

# Boundary conditions.
run_case("capture-kind-without-phase-blocked", [], 3,
         expect=("BLOCKED", "--phase is required"))
run_case("below-analysis-bar-chat-only",
         ["--phase", "accepted", "--synthesized-pages", "2",
          "--path", str(DRAFT), "--domain-context", "yes"], 0,
         expect=("chat-only",), absent=("APPROVAL REQUIRED",))
run_case(
    "exactly-300-words-stays-below-analysis-bar",
    ["--phase", "accepted", "--synthesized-pages", "3",
     "--path", str(DRAFT_300), "--domain-context", "yes"],
    0,
    expect=("chat-only",),
)
run_case(
    "exactly-301-words-crosses-analysis-bar",
    ["--phase", "accepted", "--synthesized-pages", "3",
     "--path", str(DRAFT_301), "--domain-context", "yes",
     "--primary-home", "wiki/analyses/threshold.md",
     "--pages-touched", "wiki/analyses/threshold.md"],
    2,
    expect=("analysis-capture", "APPROVAL REQUIRED"),
)
run_case(
    "domain-context-no-stays-below-analysis-bar",
    ["--phase", "accepted", "--synthesized-pages", "3",
     "--path", str(DRAFT_301), "--domain-context", "no"],
    0,
    expect=("chat-only",),
)
run_case(
    "domain-context-yes-crosses-analysis-bar",
    ["--phase", "accepted", "--synthesized-pages", "3",
     "--path", str(DRAFT_301), "--domain-context", "yes",
     "--primary-home", "wiki/analyses/domain-context.md",
     "--pages-touched", "wiki/analyses/domain-context.md"],
    2,
    expect=("analysis-capture", "APPROVAL REQUIRED"),
)
for trigger in (
    "reusable_distinction",
    "ranking_or_framework",
    "open_question_resolution",
    "future_agent_behavior",
    "existing_page_update",
):
    run_case(
        f"promotion-trigger-{trigger}-crosses-boundary",
        ["--phase", "accepted", "--trigger", trigger,
         "--primary-home", f"wiki/concepts/{trigger.replace('_', '-')}.md",
         "--pages-touched", f"wiki/concepts/{trigger.replace('_', '-')}.md"],
        2,
        expect=("promotion-audit", "APPROVAL REQUIRED"),
    )
run_case(
    "non-analysis-measured-promotion-does-not-require-authored-parse",
    ["--phase", "accepted", "--trigger", "existing_page_update",
     "--path", str(MALFORMED_FRONTMATTER_DRAFT),
     "--primary-home", "wiki/concepts/malformed-draft.md",
     "--pages-touched", "wiki/concepts/malformed-draft.md"],
    2,
    expect=("promotion-audit", "APPROVAL REQUIRED"),
    absent=("malformed frontmatter",),
)
# Determinism guards: the gate cannot be talked around.
run_case("free-route-cannot-target-analyses",
         ["--phase", "experience", "--primary-home", "wiki/analyses/sneaky.md",
          "--pages-touched", "wiki/analyses/sneaky.md"], 3,
         expect=("BLOCKED", "may not write to wiki/analyses/"))
run_case("free-route-analyses-dotslash-blocked",
         ["--phase", "experience", "--primary-home", "wiki/people/p.md",
          "--pages-touched", "./wiki/analyses/sneaky.md"], 3,
         expect=("BLOCKED", "must not contain '.' or '..' components"))
run_case("free-route-analyses-dotdot-blocked",
         ["--phase", "experience", "--primary-home", "wiki/people/p.md",
          "--pages-touched", "wiki/foo/../analyses/sneaky.md"], 3,
         expect=("BLOCKED", "must not contain '.' or '..' components"))
run_case("analysis-without-path-blocked",
         ["--phase", "accepted", "--synthesized-pages", "3",
          "--domain-context", "yes", "--primary-home", "wiki/analyses/real.md",
          "--trigger", "existing_page_update"], 3,
         expect=("BLOCKED", "requires --path"))
run_case("placeholder-home-blocked",
         ["--phase", "accepted", "--trigger", "reusable_distinction"], 3,
         expect=("BLOCKED", "concrete --primary-home"))
run_case("placeholder-pages-touched-blocked",
         PROMO[:6] + ["--pages-touched", "wiki/concepts/foo.md,wiki/<entity>/bar.md"], 3,
         expect=("BLOCKED", "not placeholders"))
run_case("out-of-root-scope-blocked",
         PROMO + ["--pages-touched", "wiki/concepts/foo.md,/etc/passwd"], 3,
         expect=("BLOCKED", "repository-relative"))
# Any route whose primary home is under wiki/analyses/ must measure the draft.
run_case("promotion-into-analyses-requires-path",
         ["--phase", "accepted", "--trigger", "existing_page_update",
          "--primary-home", "wiki/analyses/update.md",
          "--pages-touched", "wiki/analyses/update.md"], 3,
         expect=("BLOCKED", "requires --path"))
run_case("promotion-into-analyses-with-path-proceeds",
         ["--phase", "accepted", "--trigger", "existing_page_update",
          "--primary-home", "wiki/analyses/update.md",
          "--pages-touched", "wiki/analyses/update.md", "--path", str(DRAFT)], 2,
         expect=("promotion-audit", "APPROVAL REQUIRED"))
# The measurement rule covers the whole scope, not just the primary home: an
# analyses page named only in --pages-touched must still demand a draft.
run_case("analyses-in-pages-touched-requires-path",
         ["--phase", "accepted", "--trigger", "existing_page_update",
          "--primary-home", "wiki/concepts/foo.md",
          "--pages-touched", "wiki/concepts/foo.md,wiki/analyses/sneaky.md"], 3,
         expect=("BLOCKED", "requires --path"))
run_case("analyses-in-pages-touched-with-path-proceeds",
         ["--phase", "accepted", "--trigger", "existing_page_update",
          "--primary-home", "wiki/concepts/foo.md",
          "--pages-touched", "wiki/concepts/foo.md,wiki/analyses/sneaky.md",
          "--path", str(DRAFT)], 2,
         expect=("promotion-audit", "APPROVAL REQUIRED"))
# Case-variant spellings must not slip past the analyses rules (APFS is
# case-insensitive, so wiki/Analyses/ IS the analyses folder on disk).
run_case("case-variant-analyses-still-guarded",
         ["--phase", "experience", "--primary-home", "wiki/Analyses/sneaky.md",
          "--pages-touched", "wiki/Analyses/sneaky.md"], 3,
         expect=("BLOCKED", "may not write to wiki/analyses/"))
# An unreadable --path blocks with the precise diagnosis instead of
# misclassifying the run as chat-only.
run_case("unreadable-path-blocked-with-diagnosis",
         ["--phase", "accepted", "--synthesized-pages", "3", "--domain-context", "yes",
          "--primary-home", "wiki/analyses/x.md", "--pages-touched", "wiki/analyses/x.md",
          "--path", "tmp/does-not-exist.md"], 3,
         expect=("BLOCKED", "is not a readable file"))
run_case("short-measured-draft-cannot-reach-analyses",
         ["--phase", "accepted", "--synthesized-pages", "3", "--domain-context", "yes",
          "--primary-home", "wiki/analyses/x.md",
          "--pages-touched", "wiki/analyses/x.md", "--path", str(SHORT_DRAFT)], 3,
         expect=("BLOCKED", "may not write to wiki/analyses/"))
run_case("empty-artifact-blocked",
         ANALYSIS + ["--artifact", "   "], 3,
         expect=("BLOCKED", "non-empty"))
run_case("free-route-raw-destination-blocked",
         ["--phase", "experience", "--primary-home", "wiki/people/p.md",
          "--pages-touched", "raw/evil.md"], 3,
         expect=("BLOCKED", "outside allowed repository roots"))
run_case("free-route-out-of-root-blocked",
         ["--phase", "experience", "--primary-home", "wiki/people/p.md",
          "--pages-touched", "/etc/passwd"], 3,
         expect=("BLOCKED", "repository-relative"))

# The guards check declared inputs, not the route-derived home: a chat-only
# classification discards --primary-home, but a declared analyses or
# out-of-root destination must still block, with a hint toward measurement.
run_case("chat-only-declared-analyses-home-blocked",
         ["--phase", "accepted", "--primary-home", "wiki/analyses/foo.md"], 3,
         expect=("BLOCKED", "may not write to wiki/analyses/", "re-run with --path"))
run_case("chat-only-declared-out-of-root-home-blocked",
         ["--phase", "accepted", "--primary-home", "/etc/passwd"], 3,
         expect=("BLOCKED", "repository-relative"))
# Directory spellings are not file destinations and trailing empty components
# are rejected rather than normalized away.
run_case("analyses-trailing-slash-blocked",
         ["--phase", "experience", "--primary-home", "wiki/analyses/"], 3,
         expect=("BLOCKED", "empty components"))
# Scope entries the validator would reject must block before a record exists.
run_case("none-token-in-scope-blocked",
         PROMO[:6] + ["--pages-touched", "wiki/concepts/foo.md,none"], 3,
         expect=("BLOCKED", "'none'"))
run_case("negative-synthesized-pages-blocked",
         ["--phase", "accepted", "--synthesized-pages", "-2", "--domain-context", "yes",
          "--primary-home", "wiki/analyses/eval.md",
          "--pages-touched", "wiki/analyses/eval.md",
          "--path", str(DRAFT)], 3,
         expect=("BLOCKED", "non-negative"))
# Exact duplicate canonical scope declarations collapse to one entry; unsafe
# aliases are rejected by the separate dot-component cases above.
run_case("duplicate-scope-entries-deduped",
         PROMO[:6] + ["--pages-touched", "wiki/concepts/foo.md,wiki/concepts/foo.md"], 2,
         expect=("Pages touched: wiki/concepts/foo.md",),
         absent=("wiki/concepts/foo.md, wiki/concepts/foo.md",))
run_case("duplicate-separator-destination-blocked",
         ["--phase", "experience", "--primary-home", "wiki//people/p.md"], 3,
         expect=("BLOCKED", "empty components"))
run_case("backslash-destination-blocked",
         ["--phase", "experience", "--primary-home", "wiki\\people\\p.md"], 3,
         expect=("BLOCKED", "POSIX separators"))
run_case("uri-shaped-destination-blocked",
         ["--phase", "experience", "--primary-home", "file:wiki/people/p.md"], 3,
         expect=("BLOCKED", "URI-like"))
run_case("archive-no-longer-an-approval-root",
         ["--phase", "experience", "--primary-home", "archive/new.md"], 3,
         expect=("BLOCKED", "outside allowed repository roots"))
run_case("symlink-escape-destination-blocked",
         ["--phase", "experience", "--primary-home", "wiki/escape/new.md"], 3,
         expect=("BLOCKED", "escapes"), cwd=SANDBOX)
# argparse usage errors exit 3, never 2: exit 2 means only "approval required".
run_case("usage-error-exits-3", ["--no-such-flag"], 3)
# A short measured draft updating an EXISTING analyses page via a promotion
# trigger is the intended update path and stays approvable.
run_case("short-draft-promotion-into-analyses-approvable",
         ["--phase", "accepted", "--trigger", "existing_page_update",
          "--primary-home", "wiki/analyses/update.md",
          "--pages-touched", "wiki/analyses/update.md", "--path", str(SHORT_DRAFT)], 2,
         expect=("promotion-audit", "APPROVAL REQUIRED"))


# Synthesis approval branch. SYNTHESIS intentionally passes no --phase, so this
# guards the parser-level optionality required by --kind=synthesis.
run_case(
    "synthesis-requires-approval",
    SYNTHESIS,
    2,
    expect=("CAPTURE GATE", "APPROVAL REQUIRED", "Drafts for review:",
            "wiki/primer.md local-AI routing row", "Do not update wiki/synthesis.md"),
    absent=("APPROVAL CONFIRMED",),
)
check_live_ledger_unchanged("flat-synthesis-writes-no-record")
run_case(
    "synthesis-ledger-scope-required",
    ["--kind", "synthesis",
     "--drafts", "wiki/primer.md local-AI routing row",
     "--pages-touched", "wiki/primer.md,wiki/log.md"],
    3,
    expect=("CAPTURE GATE: BLOCKED", "primary home wiki/synthesis.md must be included in --pages-touched"),
)
run_case(
    "synthesis-primary-home-scope-required",
    ["--kind", "synthesis",
     "--drafts", "wiki/overview.md exact reviewed update",
     "--primary-home", "wiki/overview.md",
     "--pages-touched", "wiki/log.md"],
    3,
    expect=("CAPTURE GATE: BLOCKED", "primary home wiki/overview.md must be included in --pages-touched"),
)
run_case(
    "synthesis-drafts-required",
    ["--kind", "synthesis",
     "--drafts", " ",
     "--pages-touched", "wiki/primer.md,wiki/synthesis.md,wiki/log.md"],
    3,
    expect=("CAPTURE GATE: BLOCKED", "requires --drafts"),
)
run_case(
    "synthesis-empty-artifact-blocked",
    ["--kind", "synthesis",
     "--drafts", "wiki/primer.md local-AI routing row",
     "--pages-touched", "wiki/primer.md,wiki/synthesis.md,wiki/log.md",
     "--artifact", "   "],
    3,
    expect=("CAPTURE GATE: BLOCKED", "non-empty"),
)
run_case(
    "synthesis-raw-destination-blocked",
    ["--kind", "synthesis",
     "--drafts", "wiki/primer.md local-AI routing row",
     "--pages-touched", "wiki/synthesis.md,raw/evil.md"],
    3,
    expect=("CAPTURE GATE: BLOCKED", "outside allowed repository roots"),
)
run_case(
    "synthesis-placeholder-scope-blocked",
    ["--kind", "synthesis",
     "--drafts", "wiki/primer.md local-AI routing row",
     "--pages-touched", "wiki/synthesis.md,wiki/<entity>/x.md"],
    3,
    expect=("CAPTURE GATE: BLOCKED", "not placeholders"),
)
# The synthesis branch is unmeasured, so it may only touch analyses pages that
# already exist; a NEW analyses destination must go through analysis-capture.
run_case(
    "synthesis-new-analyses-page-blocked",
    ["--kind", "synthesis",
     "--drafts", "status flip for a page that does not exist",
     "--pages-touched", "wiki/synthesis.md,wiki/analyses/missing-eval.md"],
    3,
    expect=("CAPTURE GATE: BLOCKED", "existing", "analysis-capture"),
    cwd=SANDBOX,
)
check_workflow_contract()

exit_code = results.finish()
TMP.cleanup()
sys.exit(exit_code)
