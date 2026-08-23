#!/usr/bin/env python3
"""Regression eval for capture_gate.py.

The gate is the approval boundary between an agent and durable analysis,
promotion, or synthesis writes. This suite pins which routes require approval,
which proceed freely, which are blocked, and whether gate-created ledgers
validate against validate_capture_runs.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import ledger_common
from _durable_files import stable_lock
from _wiki_parse import canonical_authored_text
from capture_gate import DEFAULT_APPROVAL_LEDGER, LEDGER_SCHEMA_DESCRIPTION
from eval_lib import Results
from validate_capture_runs import validate_approval

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "capture_gate.py"
VALIDATOR = REPO_ROOT / "scripts" / "validate_capture_runs.py"
SYNTHESIZE_WORKFLOW = REPO_ROOT / "workflows" / "maintenance" / "synthesize.md"
TMP = tempfile.TemporaryDirectory()
APPROVAL_LEDGER = Path(TMP.name) / "capture-runs.jsonl"
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

results.record(
    "default-approval-ledger-anchored-to-repo",
    Path(DEFAULT_APPROVAL_LEDGER) == REPO_ROOT / "scripts" / "capture-runs.jsonl",
    f"default ledger: {DEFAULT_APPROVAL_LEDGER!r}",
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(name, args, expect_code, expect=(), absent=(), cwd=None):
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--artifact",
            "eval fixture",
            "--approval-ledger",
            str(APPROVAL_LEDGER),
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


def approval_records_from(path: Path, record_type: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("record_type") == record_type:
            out.append(record)
    return out


def approval_records(record_type):
    return approval_records_from(APPROVAL_LEDGER, record_type)


def check_no_ledger(name):
    ok = not APPROVAL_LEDGER.exists()
    detail = "" if ok else "unexpected ledger: " + APPROVAL_LEDGER.read_text().replace("\n", " | ")
    results.record(name, ok, detail)


def check_record_count(name, record_type, expected_count):
    count = len(approval_records(record_type))
    ok = count == expected_count
    results.record(name, ok, f"{record_type} count {count} (expected {expected_count})")


def check_gate_created_ledger_validates(name):
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), str(APPROVAL_LEDGER)],
        text=True, capture_output=True,
    )
    ok = proc.returncode == 0
    results.record(name, ok, "validator: " + proc.stdout.replace("\n", " | "))


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


def compact_line(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def check_corrupt_existing_ledger(
    name: str, content: bytes, *expected_markers: str
) -> None:
    ledger = Path(TMP.name) / f"{name}.jsonl"
    ledger.write_bytes(content)
    before = ledger.read_bytes()
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--artifact",
            "eval fixture",
            "--approval-ledger",
            str(ledger),
            *ANALYSIS,
            "--approved",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    output = proc.stdout + proc.stderr
    after = ledger.read_bytes()
    ok = (
        proc.returncode == 3
        and "CAPTURE GATE: BLOCKED" in output
        and all(marker in output for marker in expected_markers)
        and "APPROVAL CONFIRMED" not in output
        and "Approval: confirmed" not in output
        and "Structured approval record" not in output
        and "Traceback" not in output
        and before == after
    )
    detail = (
        f"exit={proc.returncode}; bytes_unchanged={before == after}; "
        f"output={output.replace(chr(10), ' | ')}"
    )
    results.record(name, ok, detail)


def check_existing_ledger_fail_closed_cases() -> None:
    schema = {
        "record_type": "schema",
        "schema_version": 1,
        "description": LEDGER_SCHEMA_DESCRIPTION,
    }
    valid = capture_record_fixture(draft_sha256=file_sha256(DRAFT))
    invalid = dict(valid)
    invalid["word_count"] = 2
    post_cutoff_analysis_unmeasured = {
        **valid,
        "approved_at": "2026-07-09T00:00:00Z",
        "word_count_source": "unmeasured",
        "word_count_path": "",
    }
    post_cutoff_analysis_unmeasured.pop("draft_sha256")
    post_cutoff_promotion_unmeasured = {
        **post_cutoff_analysis_unmeasured,
        "route": "promotion-audit",
        "triggers": ["existing_page_update"],
    }
    measured_missing_evidence = {
        **valid,
        "approved_at": "2026-07-09T00:00:00Z",
        "route": "promotion-audit",
        "primary_home": "wiki/concepts/fixture.md",
        "pages_touched": ["wiki/concepts/fixture.md"],
        "triggers": ["existing_page_update"],
        "word_count_source": "measured",
        "word_count_path": "",
    }
    measured_missing_evidence.pop("draft_sha256")
    unmeasured_with_evidence = {
        **valid,
        "approved_at": "2026-07-09T00:00:00Z",
        "route": "promotion-audit",
        "primary_home": "wiki/concepts/fixture.md",
        "pages_touched": ["wiki/concepts/fixture.md"],
        "triggers": ["existing_page_update"],
        "word_count_source": "unmeasured",
    }
    deeply_nested = "[" * 1200 + "0" + "]" * 1200
    deep_valid_line = (
        compact_line(valid)[:-1] + ',"extra":' + deeply_nested + "}"
    )
    unhashable_fields = dict(valid)
    unhashable_fields.update({
        "route": [],
        "phase": [],
        "word_count_source": [],
        "triggers": [[]],
    })
    cases = (
        ("gate-corrupt-json-fails-closed", b'{not-json\n', ("invalid JSON",)),
        ("gate-non-utf8-ledger-fails-closed", b"\xff\n", ("UTF-8",)),
        (
            "gate-overnested-json-fails-closed",
            (deeply_nested + "\n").encode(),
            ("invalid JSON",),
        ),
        (
            "gate-overnested-valid-record-fails-closed",
            (compact_line(schema) + "\n" + deep_valid_line + "\n").encode(),
            (),
        ),
        ("gate-non-object-line-fails-closed", b'[]\n', ("JSON object",)),
        (
            "gate-unhashable-record-type-fails-closed",
            (compact_line({"record_type": []}) + "\n").encode(),
            ("unsupported record_type",),
        ),
        (
            "gate-missing-schema-fails-closed",
            (compact_line(valid) + "\n").encode(),
            ("schema",),
        ),
        (
            "gate-duplicate-schema-fails-closed",
            (compact_line(schema) + "\n" + compact_line(schema) + "\n").encode(),
            ("schema",),
        ),
        (
            "gate-misplaced-schema-fails-closed",
            (compact_line(valid) + "\n" + compact_line(schema) + "\n").encode(),
            ("schema",),
        ),
        (
            "gate-invalid-existing-record-fails-closed",
            (compact_line(schema) + "\n" + compact_line(invalid) + "\n").encode(),
            ("analysis-capture",),
        ),
        (
            "gate-post-cutoff-analysis-unmeasured-fails-closed",
            (
                compact_line(schema)
                + "\n"
                + compact_line(post_cutoff_analysis_unmeasured)
                + "\n"
            ).encode(),
            ("analyses-targeting", "measured"),
        ),
        (
            "gate-post-cutoff-analysis-promotion-unmeasured-fails-closed",
            (
                compact_line(schema)
                + "\n"
                + compact_line(post_cutoff_promotion_unmeasured)
                + "\n"
            ).encode(),
            ("analyses-targeting", "measured"),
        ),
        (
            "gate-measured-missing-evidence-fails-closed",
            (
                compact_line(schema)
                + "\n"
                + compact_line(measured_missing_evidence)
                + "\n"
            ).encode(),
            ("word_count_path", "draft_sha256"),
        ),
        (
            "gate-unmeasured-with-evidence-fails-closed",
            (
                compact_line(schema)
                + "\n"
                + compact_line(unmeasured_with_evidence)
                + "\n"
            ).encode(),
            ("empty word_count_path", "must not carry draft_sha256"),
        ),
        (
            "gate-unhashable-existing-fields-fail-closed",
            (
                compact_line(schema)
                + "\n"
                + compact_line(unhashable_fields)
                + "\n"
            ).encode(),
            ("route must be", "word_count_source", "triggers must be"),
        ),
        (
            "gate-duplicate-plus-corrupt-tail-fails-closed",
            (
                compact_line(schema)
                + "\n"
                + compact_line(valid)
                + "\n"
                + compact_line(valid)
                + "\n{bad-tail\n"
            ).encode(),
            ("duplicate approval", "invalid JSON"),
        ),
        ("gate-whitespace-only-ledger-fails-closed", b"  \n\t\n", ("whitespace",)),
    )
    for name, content, markers in cases:
        check_corrupt_existing_ledger(name, content, *markers)


def check_writer_hash_lookup_and_candidate_validation() -> None:
    ledger = Path(TMP.name) / "writer-hash-ledger.jsonl"
    record = capture_record_fixture(draft_sha256=file_sha256(DRAFT))
    invalid = dict(record)
    invalid["word_count"] = 2
    nested_invalid = Path(TMP.name) / "must-not-be-created" / "ledger.jsonl"
    details: list[str] = []
    ok = True
    try:
        first = ledger_common.write_approval_record(
            ledger,
            record,
            "capture_approval",
            LEDGER_SCHEMA_DESCRIPTION,
            validate_approval,
        )
        first_bytes = ledger.read_bytes()
        second = ledger_common.write_approval_record(
            ledger,
            record,
            "capture_approval",
            LEDGER_SCHEMA_DESCRIPTION,
            validate_approval,
        )
        second_bytes = ledger.read_bytes()
        wrote_first, _path_first, _label_first, first_hash = first
        wrote_second, _path_second, _label_second, second_hash = second
        expected_hash = hashlib.sha256(first_bytes.split(b"\n")[1]).hexdigest()
        lookup = ledger_common.lookup_approval_record_by_sha256(
            ledger,
            first_hash,
            ledger_common.APPROVAL_RECORD_TYPES,
            validate_approval,
        )
        ok = ok and (
            wrote_first is True
            and wrote_second is False
            and first_hash == second_hash
            and first_hash == expected_hash
            and len(first_hash) == 64
            and first_bytes == second_bytes
            and lookup == record
        )
    except Exception as exc:
        ok = False
        details.append(f"hash/idempotence error: {type(exc).__name__}: {exc}")

    zero_ledger = Path(TMP.name) / "zero-byte-ledger.jsonl"
    zero_ledger.write_bytes(b"")
    try:
        zero_result = ledger_common.write_approval_record(
            zero_ledger,
            {**record, "artifact": "zero byte fixture"},
            "capture_approval",
            LEDGER_SCHEMA_DESCRIPTION,
            validate_approval,
        )
        zero_lines = zero_ledger.read_text(encoding="utf-8").splitlines()
        ok = ok and zero_result[0] is True and len(zero_lines) == 2
    except Exception as exc:
        ok = False
        details.append(f"zero-byte error: {type(exc).__name__}: {exc}")

    try:
        ledger_common.write_approval_record(
            nested_invalid,
            invalid,
            "capture_approval",
            LEDGER_SCHEMA_DESCRIPTION,
            validate_approval,
        )
    except Exception as exc:
        integrity_type = getattr(ledger_common, "LedgerIntegrityError", ())
        ok = ok and isinstance(exc, integrity_type) and not nested_invalid.parent.exists()
    else:
        ok = False
        details.append("invalid candidate unexpectedly wrote")

    existing_before = ledger.read_bytes() if ledger.exists() else b""
    try:
        ledger_common.write_approval_record(
            ledger,
            invalid,
            "capture_approval",
            LEDGER_SCHEMA_DESCRIPTION,
            validate_approval,
        )
    except Exception as exc:
        integrity_type = getattr(ledger_common, "LedgerIntegrityError", ())
        ok = (
            ok
            and isinstance(exc, integrity_type)
            and ledger.read_bytes() == existing_before
        )
    else:
        ok = False
        details.append("invalid candidate changed existing ledger")

    deep_candidate_value: object = 0
    for _ in range(1200):
        deep_candidate_value = [deep_candidate_value]
    for suffix, candidate, candidate_type in (
        (
            "record-type",
            {**record, "record_type": "unknown_approval"},
            "unknown_approval",
        ),
        (
            "backfilled",
            {**record, "backfilled": True, "backfill_source": "fixture"},
            "capture_approval",
        ),
        (
            "overnested",
            {**record, "extra": deep_candidate_value},
            "capture_approval",
        ),
    ):
        path = Path(TMP.name) / f"must-not-create-{suffix}" / "ledger.jsonl"
        try:
            ledger_common.write_approval_record(
                path,
                candidate,
                candidate_type,
                LEDGER_SCHEMA_DESCRIPTION,
                validate_approval,
            )
        except Exception as exc:
            integrity_type = getattr(ledger_common, "LedgerIntegrityError", ())
            ok = ok and isinstance(exc, integrity_type) and not path.parent.exists()
        else:
            ok = False
            details.append(f"{suffix} candidate unexpectedly wrote")

    corrupt = Path(TMP.name) / "lookup-corrupt.jsonl"
    corrupt.write_text("{bad\n", encoding="utf-8")
    try:
        ledger_common.lookup_approval_record_by_sha256(
            corrupt,
            "0" * 64,
            ledger_common.APPROVAL_RECORD_TYPES,
            validate_approval,
        )
    except Exception as exc:
        integrity_type = getattr(ledger_common, "LedgerIntegrityError", ())
        ok = ok and isinstance(exc, integrity_type)
    else:
        ok = False
        details.append("corrupt lookup unexpectedly returned")

    results.record(
        "writer-returns-stable-record-hash-and-validated-lookup",
        ok,
        "; ".join(details),
    )


def check_authored_hash_and_trigger_canonicalization() -> None:
    draft = Path(TMP.name) / "authored-hash-draft.md"
    draft_text = (
        "---\ntitle: Hash fixture\ntype: analysis\n---\n\n"
        + "word " * 310
        + "\n\n## Related pages\n\n- Related: [[primer]]\n"
    )
    draft.write_text(draft_text, encoding="utf-8")
    final_text = draft_text + "\n## Referenced by\n\n- [[index]]\n"
    authored_hash = hashlib.sha256(
        canonical_authored_text(draft_text).encode("utf-8")
    ).hexdigest()
    final_authored_hash = hashlib.sha256(
        canonical_authored_text(final_text).encode("utf-8")
    ).hexdigest()
    ledger = Path(TMP.name) / "authored-hash-ledger.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--artifact",
            "authored hash fixture",
            "--approval-ledger",
            str(ledger),
            "--phase",
            "accepted",
            "--synthesized-pages",
            "3",
            "--domain-context",
            "yes",
            "--primary-home",
            "wiki/analyses/authored-hash.md",
            "--pages-touched",
            "wiki/analyses/authored-hash.md,wiki/log.md",
            "--path",
            str(draft),
            "--approved",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    records = approval_records_from(ledger, "capture_approval")
    record = records[0] if len(records) == 1 else {}
    ok = (
        proc.returncode == 0
        and authored_hash == final_authored_hash
        and authored_hash != hashlib.sha256(final_text.encode("utf-8")).hexdigest()
        and record.get("authored_sha256") == authored_hash
        and record.get("authored_hash_policy") == "strip_referenced_by_v1"
        and "Approval record SHA-256:" in proc.stdout
    )
    results.record(
        "gate-binds-canonical-authored-hash",
        ok,
        f"exit={proc.returncode}; record={record!r}; stdout={proc.stdout!r}",
    )

    trigger_ledger = Path(TMP.name) / "canonical-trigger-ledger.jsonl"
    trigger_proc = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--artifact",
            "trigger fixture",
            "--approval-ledger",
            str(trigger_ledger),
            "--phase",
            "accepted",
            "--trigger",
            "reusable_distinction",
            "--trigger",
            "reusable_distinction",
            "--primary-home",
            "wiki/concepts/trigger-fixture.md",
            "--pages-touched",
            "wiki/concepts/trigger-fixture.md",
            "--approved",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    trigger_records = approval_records_from(trigger_ledger, "capture_approval")
    trigger_record = trigger_records[0] if len(trigger_records) == 1 else {}
    results.record(
        "duplicate-trigger-flags-collapse-before-identity",
        trigger_proc.returncode == 0
        and trigger_record.get("triggers") == ["reusable_distinction"],
        f"exit={trigger_proc.returncode}; record={trigger_record!r}; "
        f"output={(trigger_proc.stdout + trigger_proc.stderr)!r}",
    )


def check_approval_ledger_contention() -> None:
    ledger = Path(TMP.name) / "contention-capture-runs.jsonl"
    record = capture_record_fixture(
        artifact="contention fixture",
        draft_sha256="a" * 64,
    )
    child_code = """
import json
import sys
from pathlib import Path

from ledger_common import write_approval_record
from validate_capture_runs import validate_approval

ledger = Path(sys.argv[1])
record = json.loads(sys.argv[2])
schema_description = sys.argv[3]
print("READY", flush=True)
wrote, path, label, record_hash = write_approval_record(
    ledger, record, "capture_approval", schema_description, validate_approval
)
print(json.dumps({"wrote": wrote, "path": str(path), "label": label,
                  "record_hash": record_hash}), flush=True)
"""
    schema = {
        "record_type": "schema",
        "schema_version": 1,
        "description": LEDGER_SCHEMA_DESCRIPTION,
    }
    payload = (
        json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\n"
        + json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    )

    child = None
    ready = ""
    completed_while_locked = False
    child_stdout = ""
    child_stderr = ""
    with stable_lock(ledger_common.approval_lock_path(ledger)):
        with ledger.open("a+", encoding="utf-8") as locked:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(ledger),
                    json.dumps(record),
                    LEDGER_SCHEMA_DESCRIPTION,
                ],
                cwd=REPO_ROOT / "scripts",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert child.stdout is not None
            ready = child.stdout.readline().strip()
            try:
                child.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                completed_while_locked = False
            else:
                completed_while_locked = True
            locked.write(payload)
            locked.flush()

    if child is not None:
        try:
            child_stdout, child_stderr = child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child_stdout, child_stderr = child.communicate()

    child_result: dict[str, object] = {}
    output_lines = [line for line in child_stdout.splitlines() if line.strip()]
    if output_lines:
        try:
            child_result = json.loads(output_lines[-1])
        except json.JSONDecodeError:
            child_result = {}
    schema_count = len(approval_records_from(ledger, "schema"))
    approval_count = len(approval_records_from(ledger, "capture_approval"))
    validator = subprocess.run(
        [sys.executable, str(VALIDATOR), str(ledger)],
        text=True,
        capture_output=True,
        check=False,
    )
    ok = (
        ready == "READY"
        and child is not None
        and child.returncode == 0
        and child_result.get("wrote") is False
        and schema_count == 1
        and approval_count == 1
        and validator.returncode == 0
    )
    detail = (
        f"ready={ready!r}; completed_while_locked(best-effort)={completed_while_locked}; "
        f"child_result={child_result!r}; child_stderr={child_stderr!r}; "
        f"schema_count={schema_count}; approval_count={approval_count}; "
        f"validator_exit={validator.returncode}; "
        f"validator_stdout={validator.stdout.replace(chr(10), ' | ')}; "
        f"ledger={ledger.read_text(encoding='utf-8').replace(chr(10), ' | ')}"
    )
    results.record("approval-ledger-contention-is-idempotent", ok, detail)


def check_parallel_approval_writers() -> None:
    child_code = """
import json
import sys
from pathlib import Path
from ledger_common import write_approval_record
from validate_capture_runs import validate_approval
print('READY', flush=True)
sys.stdin.readline()
result = write_approval_record(
    Path(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3], sys.argv[4], validate_approval
)
print(json.dumps({'wrote': result[0], 'hash': result[3]}), flush=True)
"""

    def run_group(ledger: Path, records: list[dict]) -> tuple[list[dict], str]:
        children = []
        ready = []
        for record in records:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(ledger),
                    json.dumps(record),
                    record["record_type"],
                    LEDGER_SCHEMA_DESCRIPTION,
                ],
                cwd=REPO_ROOT / "scripts",
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert proc.stdout is not None
            ready.append(proc.stdout.readline().strip())
            children.append(proc)
        for proc in children:
            assert proc.stdin is not None
            proc.stdin.write("go\n")
            proc.stdin.flush()
            proc.stdin.close()
        parsed: list[dict] = []
        details: list[str] = []
        for proc in children:
            assert proc.stdout is not None and proc.stderr is not None
            stdout = proc.stdout.read()
            stderr = proc.stderr.read()
            proc.wait(timeout=10)
            details.append(f"exit={proc.returncode} stdout={stdout!r} stderr={stderr!r}")
            if proc.returncode == 0 and stdout.strip():
                parsed.append(json.loads(stdout.splitlines()[-1]))
        return parsed, f"ready={ready}; " + "; ".join(details)

    same_ledger = Path(TMP.name) / "parallel-same.jsonl"
    same_record = capture_record_fixture(artifact="parallel same", draft_sha256="c" * 64)
    same_results, same_detail = run_group(same_ledger, [same_record] * 8)
    same_validation = subprocess.run(
        [sys.executable, str(VALIDATOR), str(same_ledger)], capture_output=True, text=True
    )
    results.record(
        "parallel-same-event-writers-are-exactly-idempotent",
        len(same_results) == 8
        and sum(bool(item["wrote"]) for item in same_results) == 1
        and len({item["hash"] for item in same_results}) == 1
        and len(approval_records_from(same_ledger, "capture_approval")) == 1
        and same_validation.returncode == 0,
        same_detail,
    )

    distinct_ledger = Path(TMP.name) / "parallel-distinct.jsonl"
    distinct_records = [
        capture_record_fixture(artifact=f"parallel distinct {index}", draft_sha256=f"{index:x}" * 64)
        for index in range(1, 9)
    ]
    distinct_results, distinct_detail = run_group(distinct_ledger, distinct_records)
    distinct_validation = subprocess.run(
        [sys.executable, str(VALIDATOR), str(distinct_ledger)], capture_output=True, text=True
    )
    results.record(
        "parallel-distinct-event-writers-have-no-lost-records",
        len(distinct_results) == 8
        and all(item["wrote"] for item in distinct_results)
        and len(approval_records_from(distinct_ledger, "capture_approval")) == 8
        and distinct_validation.returncode == 0,
        distinct_detail,
    )


def check_atomic_ledger_faults_and_entry_types() -> None:
    import os

    base = capture_record_fixture(artifact="fault base", draft_sha256="d" * 64)
    candidate = capture_record_fixture(artifact="fault candidate", draft_sha256="e" * 64)
    stages = (
        "before_write", "after_write", "after_file_fsync", "before_replace",
        "after_replace", "after_dir_fsync", "before_reopen", "after_reopen", "after_verify",
    )
    all_ok = True
    details: list[str] = []
    for stage in stages:
        ledger = Path(TMP.name) / f"ledger-fault-{stage}.jsonl"
        ledger_common.write_approval_record(
            ledger, base, "capture_approval", LEDGER_SCHEMA_DESCRIPTION, validate_approval
        )
        try:
            ledger_common.write_approval_record(
                ledger,
                candidate,
                "capture_approval",
                LEDGER_SCHEMA_DESCRIPTION,
                validate_approval,
                fault=lambda current, wanted=stage: (_ for _ in ()).throw(RuntimeError(wanted)) if current == wanted else None,
            )
        except RuntimeError:
            pass
        except Exception as exc:
            # DurableFileError is wrapped as LedgerIntegrityError before replace.
            if stage not in {"before_write", "after_write", "after_file_fsync", "before_replace"}:
                details.append(f"{stage}: unexpected {type(exc).__name__}: {exc}")
        errors, count = ledger_common.validate_ledger(
            ledger, ledger_common.APPROVAL_RECORD_TYPES, validate_approval
        )
        if errors or count not in {1, 2}:
            all_ok = False
            details.append(f"{stage}: errors={errors} count={count}")
        rerun = ledger_common.write_approval_record(
            ledger, candidate, "capture_approval", LEDGER_SCHEMA_DESCRIPTION, validate_approval
        )
        errors, count = ledger_common.validate_ledger(
            ledger, ledger_common.APPROVAL_RECORD_TYPES, validate_approval
        )
        if errors or count != 2:
            all_ok = False
            details.append(f"{stage}: rerun={rerun} errors={errors} count={count}")
    results.record("ledger-fault-matrix-leaves-validator-clean-old-or-new", all_ok, "; ".join(details))

    killed_ledger = Path(TMP.name) / "ledger-process-kill-after-replace.jsonl"
    ledger_common.write_approval_record(
        killed_ledger, base, "capture_approval", LEDGER_SCHEMA_DESCRIPTION, validate_approval
    )
    kill_code = """
import json
import os
import sys
from pathlib import Path
from ledger_common import write_approval_record
from validate_capture_runs import validate_approval
write_approval_record(
    Path(sys.argv[1]), json.loads(sys.argv[2]), 'capture_approval', sys.argv[3],
    validate_approval,
    fault=lambda stage: os._exit(88) if stage == 'after_replace' else None,
)
"""
    killed = subprocess.run(
        [
            sys.executable,
            "-c",
            kill_code,
            str(killed_ledger),
            json.dumps(candidate),
            LEDGER_SCHEMA_DESCRIPTION,
        ],
        cwd=REPO_ROOT / "scripts",
        capture_output=True,
        text=True,
        check=False,
    )
    killed_errors, killed_count = ledger_common.validate_ledger(
        killed_ledger, ledger_common.APPROVAL_RECORD_TYPES, validate_approval
    )
    killed_retry = ledger_common.write_approval_record(
        killed_ledger,
        candidate,
        "capture_approval",
        LEDGER_SCHEMA_DESCRIPTION,
        validate_approval,
    )
    results.record(
        "ledger-process-kill-after-replace-is-valid-and-idempotent",
        killed.returncode == 88
        and not killed_errors
        and killed_count == 2
        and killed_retry[0] is False,
        f"exit={killed.returncode} errors={killed_errors} count={killed_count} retry={killed_retry}",
    )

    unsafe_ok = True
    unsafe_details: list[str] = []
    for kind in ("symlink", "hardlink", "directory", "fifo"):
        ledger = Path(TMP.name) / f"unsafe-ledger-{kind}.jsonl"
        anchor = Path(TMP.name) / f"unsafe-anchor-{kind}.jsonl"
        anchor.write_text("anchor\n", encoding="utf-8")
        if kind == "symlink":
            ledger.symlink_to(anchor)
        elif kind == "hardlink":
            os.link(anchor, ledger)
        elif kind == "directory":
            ledger.mkdir()
        else:
            os.mkfifo(ledger)
        try:
            ledger_common.write_approval_record(
                ledger, base, "capture_approval", LEDGER_SCHEMA_DESCRIPTION, validate_approval
            )
        except ledger_common.LedgerIntegrityError:
            pass
        else:
            unsafe_ok = False
            unsafe_details.append(f"accepted {kind}")
    results.record("ledger-unsafe-entry-types-fail-closed", unsafe_ok, "; ".join(unsafe_details))

    live_bytes = (REPO_ROOT / "scripts/capture-runs.jsonl").read_bytes()
    live_validation = ledger_common.validate_ledger_text(
        live_bytes.decode("utf-8"), ledger_common.APPROVAL_RECORD_TYPES, validate_approval
    )
    copy_path = Path(TMP.name) / "production-ledger-copy.jsonl"
    copy_path.write_bytes(live_bytes)
    if live_validation.approvals:
        existing_record = live_validation.approvals[-1].record
        expected_bytes = live_bytes
    else:
        ledger_common.write_approval_record(
            copy_path,
            base,
            "capture_approval",
            LEDGER_SCHEMA_DESCRIPTION,
            validate_approval,
        )
        existing_record = base
        expected_bytes = copy_path.read_bytes()
    no_op = ledger_common.write_approval_record(
        copy_path,
        existing_record,
        existing_record["record_type"],
        LEDGER_SCHEMA_DESCRIPTION,
        validate_approval,
    )
    results.record(
        "production-ledger-copy-is-byte-identical-after-idempotent-write",
        not live_validation.errors and no_op[0] is False and copy_path.read_bytes() == expected_bytes,
        f"errors={live_validation.errors} no_op={no_op}",
    )


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


def check_changed_draft_hash_identity() -> None:
    ledger = Path(TMP.name) / "changed-draft-capture-runs.jsonl"
    draft = Path(TMP.name) / "changed-draft.md"
    draft.write_text("same " * 350)
    args = [
        sys.executable,
        str(GATE),
        "--artifact",
        "changed draft fixture",
        "--approval-ledger",
        str(ledger),
        "--phase",
        "accepted",
        "--synthesized-pages",
        "3",
        "--domain-context",
        "yes",
        "--primary-home",
        "wiki/analyses/changed-draft.md",
        "--pages-touched",
        "wiki/analyses/changed-draft.md,wiki/log.md",
        "--path",
        str(draft),
        "--approved",
    ]
    first_hash = file_sha256(draft)
    first = subprocess.run(args, text=True, capture_output=True, check=False)
    first_records = approval_records_from(ledger, "capture_approval")
    second = subprocess.run(args, text=True, capture_output=True, check=False)
    second_records = approval_records_from(ledger, "capture_approval")
    draft.write_text("changed " * 350)
    changed_hash = file_sha256(draft)
    third = subprocess.run(args, text=True, capture_output=True, check=False)
    third_records = approval_records_from(ledger, "capture_approval")

    ok = (
        first.returncode == 0
        and second.returncode == 0
        and third.returncode == 0
        and len(first_records) == 1
        and first_records[0].get("draft_sha256") == first_hash
        and len(second_records) == 1
        and "already present" in second.stdout
        and len(third_records) == 2
        and {record.get("draft_sha256") for record in third_records}
        == {first_hash, changed_hash}
        and "appended" in third.stdout
    )
    detail = (
        f"exits: {first.returncode}, {second.returncode}, {third.returncode}; "
        f"counts: {len(first_records)}, {len(second_records)}, {len(third_records)}; "
        f"hashes: {[record.get('draft_sha256') for record in third_records]!r}; "
        f"second stdout: {second.stdout.replace(chr(10), ' | ')}; "
        f"third stdout: {third.stdout.replace(chr(10), ' | ')}"
    )
    results.record("changed-measured-draft-appends-new-approval", ok, detail)


def check_synthesis_record() -> None:
    records = approval_records("synthesis_approval")
    ok = (
        len(records) == 1
        and records[0].get("record_type") == "synthesis_approval"
        and records[0].get("approval_status") == "approved"
        and records[0].get("primary_home") == "wiki/synthesis.md"
        and records[0].get("ledger_update_required") is True
        and records[0].get("pages_touched") == ["wiki/primer.md", "wiki/synthesis.md", "wiki/log.md"]
        and all(
            key not in records[0]
            for key in (
                "word_count_source",
                "word_count_path",
                "draft_sha256",
                "authored_sha256",
                "authored_hash_policy",
            )
        )
        and "run_id" not in records[0]
    )
    results.record("synthesis-approved-writes-structured-record", ok, "records: " + repr(records))


def check_synthesis_idempotent() -> None:
    before = approval_records("synthesis_approval")
    proc = subprocess.run(
        [sys.executable, str(GATE), "--artifact", "eval fixture",
         "--approval-ledger", str(APPROVAL_LEDGER), *SYNTHESIS, "--approved"],
        text=True,
        capture_output=True,
        check=False,
    )
    after = approval_records("synthesis_approval")
    ok = (
        proc.returncode == 0
        and len(before) == 1
        and before == after
        and "already present" in proc.stdout
    )
    results.record("synthesis-approved-structured-record-idempotent", ok,
                   f"exit {proc.returncode}; stdout: " + proc.stdout.replace("\n", " | ")
                   + f"; before: {before!r}; after: {after!r}")


def check_approved_synthesis_existing_analysis() -> None:
    ledger = Path(TMP.name) / "existing-analysis-synthesis-ledger.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--artifact",
            "existing analysis synthesis fixture",
            "--approval-ledger",
            str(ledger),
            "--kind",
            "synthesis",
            "--drafts",
            "status flip on the reviewed existing analysis",
            "--pages-touched",
            "wiki/synthesis.md,wiki/analyses/existing-eval.md",
            "--approved",
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=SANDBOX,
    )
    records = approval_records_from(ledger, "synthesis_approval")
    record = records[0] if len(records) == 1 else {}
    validator = subprocess.run(
        [sys.executable, str(VALIDATOR), str(ledger)],
        text=True,
        capture_output=True,
        check=False,
        cwd=SANDBOX,
    )
    capture_fields = {
        "word_count_source",
        "word_count_path",
        "draft_sha256",
        "authored_sha256",
        "authored_hash_policy",
    }
    ok = (
        proc.returncode == 0
        and validator.returncode == 0
        and len(records) == 1
        and record.get("pages_touched")
        == ["wiki/synthesis.md", "wiki/analyses/existing-eval.md"]
        and not capture_fields.intersection(record)
        and "APPROVAL CONFIRMED" in proc.stdout
    )
    results.record(
        "approved-synthesis-existing-analysis-needs-no-capture-measurement",
        ok,
        f"gate_exit={proc.returncode}; validator_exit={validator.returncode}; "
        f"record={record!r}; output={(proc.stdout + proc.stderr)!r}",
    )


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


# Approval-required capture routes: exit 2 until --approved, then 0.
check_existing_ledger_fail_closed_cases()
check_writer_hash_lookup_and_candidate_validation()
check_authored_hash_and_trigger_canonicalization()
run_case("analysis-requires-approval", ANALYSIS, 2,
         expect=("analysis-capture", "APPROVAL REQUIRED",
                 "What you are approving:",
                 'Reply with plain-language approval'),
         absent=("Reply exactly:",))
check_no_ledger("unapproved-analysis-does-not-write-structured-record")
run_case("analysis-approved-proceeds", ANALYSIS + ["--approved"], 0,
         expect=("Approval: confirmed", "Structured approval record: appended", "APPROVAL CONFIRMED"),
         absent=("APPROVAL REQUIRED",))
check_record_count("approved-analysis-writes-structured-record", "capture_approval", 1)
check_validator_draft_hash_rules()
run_case("analysis-approved-idempotent", ANALYSIS + ["--approved"], 0,
         expect=("Structured approval record: already present", "APPROVAL CONFIRMED"))
check_record_count("approved-analysis-record-stays-idempotent", "capture_approval", 1)
check_changed_draft_hash_identity()
run_case("promotion-requires-approval", PROMO, 2,
         expect=("promotion-audit", "APPROVAL REQUIRED",
                 "Durable action: Apply an artifact promotion to the wiki.",
                 "reusable distinction"))
run_case("promotion-approved-proceeds", PROMO + ["--approved"], 0,
         expect=("Structured approval record: appended",))
check_record_count("approved-promotion-writes-structured-record", "capture_approval", 2)
check_gate_created_ledger_validates("capture-gate-created-ledger-validates")

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
run_case("approved-flag-cannot-skip-block",
         ["--phase", "experience", "--approved",
          "--primary-home", "wiki/analyses/sneaky.md",
          "--pages-touched", "wiki/analyses/sneaky.md"], 3,
         expect=("BLOCKED", "may not write to wiki/analyses/"))

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
run_case("placeholder-pages-touched-blocked-even-approved",
         PROMO[:6] + ["--pages-touched", "wiki/concepts/foo.md,wiki/<entity>/bar.md",
                      "--approved"], 3,
         expect=("BLOCKED", "not placeholders"))
check_record_count("placeholder-scope-writes-no-record", "capture_approval", 2)
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
         ANALYSIS + ["--artifact", "   ", "--approved"], 3,
         expect=("BLOCKED", "non-empty"))
check_record_count("empty-artifact-writes-no-record", "capture_approval", 2)
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
         PROMO[:6] + ["--pages-touched", "wiki/concepts/foo.md,none", "--approved"], 3,
         expect=("BLOCKED", "'none'"))
check_record_count("none-scope-writes-no-record", "capture_approval", 2)
run_case("negative-synthesized-pages-blocked",
         ["--phase", "accepted", "--synthesized-pages", "-2", "--domain-context", "yes",
          "--primary-home", "wiki/analyses/eval.md",
          "--pages-touched", "wiki/analyses/eval.md",
          "--path", str(DRAFT), "--approved"], 3,
         expect=("BLOCKED", "non-negative"))
check_record_count("negative-synthesized-pages-writes-no-record", "capture_approval", 2)
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


def check_analysis_record_measurement_provenance():
    records = [r for r in approval_records("capture_approval")
               if r.get("route") == "analysis-capture"]
    expected_hash = file_sha256(DRAFT)
    ok = (
        len(records) == 1
        and records[0].get("word_count_path") == str(DRAFT)
        and records[0].get("word_count_source") == "measured"
        and records[0].get("draft_sha256") == expected_hash
    )
    results.record("analysis-record-carries-measurement-provenance", ok,
                   "records: " + repr(records))


check_analysis_record_measurement_provenance()

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
check_record_count("unapproved-synthesis-does-not-write-structured-record", "synthesis_approval", 0)
run_case(
    "synthesis-approved-proceeds",
    SYNTHESIS + ["--approved"],
    0,
    expect=("Approval: confirmed", "Structured approval record: appended",
            "APPROVAL CONFIRMED", "Proceed only within this approved scope."),
    absent=("APPROVAL REQUIRED",),
)
check_synthesis_record()
check_synthesis_idempotent()
check_gate_created_ledger_validates("merged-gate-created-ledger-validates")
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
     "--artifact", "   ",
     "--approved"],
    3,
    expect=("CAPTURE GATE: BLOCKED", "non-empty"),
)
check_synthesis_record()
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
check_approved_synthesis_existing_analysis()
check_workflow_contract()
check_approval_ledger_contention()
check_parallel_approval_writers()
check_atomic_ledger_faults_and_entry_types()

# Appending after a truncated trailing newline must not merge two records into
# one corrupt line.
APPROVAL_LEDGER.write_bytes(APPROVAL_LEDGER.read_bytes().rstrip(b"\n"))
run_case("append-after-missing-trailing-newline",
         PROMO + ["--artifact", "newline repair fixture", "--approved"], 0,
         expect=("Structured approval record: appended",))
check_gate_created_ledger_validates("ledger-validates-after-newline-repair")

exit_code = results.finish()
TMP.cleanup()
sys.exit(exit_code)
