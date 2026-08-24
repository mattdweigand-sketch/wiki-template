#!/usr/bin/env python3
"""Seeded evals for lint repository structure and Git boundaries."""

from eval_lint_fixture import *
from wiki_entity_catalog import load_entity_catalog


def write_sourcing_queue(root: Path, *markers: str) -> None:
    (root / "wiki/sourcing-queue.md").write_text(
        "# Sourcing Queue\n\n" + "\n".join(markers) + "\n",
        encoding="utf-8",
    )

# ---- Tier 1: index-row uniqueness ----
run_case(
    "index-duplicate-row-fails-tier1",
    lambda r: add_index_row(r, "concepts/alpha.md", "duplicate row"),
    expect_code=1, expect=("index-duplicate", "multiple index.md rows"),
)

# ---- Tier 1: log entry headers (the grammar rotate_log.py cuts at) ----
def write_log_text(root, text):
    (root / "wiki" / "log.md").write_text(text)


run_case(
    "log-entry-header-bad-heading-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-06-01] ingest | ok\nBody.\n\n## Random Section\nBody.\n",
    ),
    expect_code=1, expect=("log-entry-header", "not a recognized log entry header"),
)
run_case(
    "log-entry-header-valid-forms-pass-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-06-01] ingest | ok\nBody.\n\n## 2026-06-02 | plain form\nBody.\n",
    ),
)
run_case(
    # rotate_log's cuts are fence-unaware, so ANY fenced '## ' line in log.md
    # is a hazard: a fenced date-shaped header would become a bogus cut point.
    "log-entry-header-fenced-line-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-06-01] ingest | ok\nBody.\n\n"
        "```\n## [2026-06-02] fenced example\n```\n",
    ),
    expect_code=1, expect=("log-entry-header", "fenced '## ' line"),
)

# ---- Tier 2: review_by enrollment for decisions ----
# A dense body (>=80 authored words) plus an inbound link from alpha keep the
# seeded decision out of the thin and orphan listings, so its only appearance in
# lint output is the enrollment signal. That isolation is what lets the negative
# case assert the page vanishes entirely once review_by is set.
DECISION_BODY = (
    "This fixture decision exists to exercise the review_by enrollment signal. It "
    "carries a deliberately dense body so it clears the thin-page threshold and "
    "its only appearance in lint output comes from the enrollment check rather "
    "than the orphan or thin listings. The decision describes a dated choice whose "
    "realized outcome should eventually be graded against what actually happened "
    "instead of standing on self-assessed confidence forever, which is exactly "
    "the population the outcome-review loop is meant to enroll and surface for "
    "periodic grading by a human reviewer working the maintenance review task."
)


def seed_decision_without_review_by(root):
    (root / "wiki" / "decisions").mkdir(exist_ok=True)
    (root / "wiki" / "decisions" / "target.md").write_text(
        '---\ntitle: "Target"\ntype: decision\ncreated: 2026-06-01\nupdated: 2026-06-01\n'
        'sources: ["experience: lint eval fixture"]\ntags: [fixture]\nconfidence: medium\n'
        'agent_use_cases:\n  - lint eval fixture\n---\n\n'
        f'{DECISION_BODY}\n\n'
        '## Open questions / gaps\n\n- Fixture page; no real questions.\n')
    append(root, "wiki/index.md", "| [target.md](decisions/target.md) | fixture decision |\n")
    append(root, "wiki/concepts/alpha.md", "- Related: [[target]]\n")


run_case(
    "review-by-missing-fires",
    seed_decision_without_review_by,
    args=(), expect_code=0,
    expect=("with no review_by", "decisions/target.md"),
)
run_case(
    "review-by-present-not-flagged",
    lambda r: (
        seed_decision_without_review_by(r),
        edit(r, "wiki/decisions/target.md", "confidence: medium",
             "confidence: medium\nauthority_kind: none\nreview_by: 2026-12-31"),
    ),
    args=(), expect_code=0,
    absent=("decisions/target.md",),
)


def seed_goal_without_review_by(root):
    (root / "wiki" / "goals").mkdir(exist_ok=True)
    (root / "wiki" / "goals" / "target-goal.md").write_text(
        '---\ntitle: "Target Goal"\ntype: goal\ncreated: 2026-06-01\nupdated: 2026-06-01\n'
        'sources: ["experience: lint eval fixture"]\ntags: [fixture]\nconfidence: medium\n'
        'agent_use_cases:\n  - lint eval fixture\n---\n\n'
        f'{DECISION_BODY}\n\n'
        '## Open questions / gaps\n\n- Fixture page; no real questions.\n')
    append(root, "wiki/index.md", "| [target-goal.md](goals/target-goal.md) | fixture goal |\n")
    append(root, "wiki/concepts/alpha.md", "- Related: [[target-goal]]\n")


run_case(
    "goal-review-by-missing-fires",
    seed_goal_without_review_by,
    args=(), expect_code=0,
    expect=("goals and decisions with no review_by", "goals/target-goal.md"),
)
run_case(
    "goal-review-by-present-not-flagged",
    lambda r: (
        seed_goal_without_review_by(r),
        edit(r, "wiki/goals/target-goal.md", "confidence: medium",
             "confidence: medium\nauthority_kind: none\nreview_by: 2026-12-31"),
    ),
    args=(), expect_code=0,
    absent=("goals/target-goal.md",),
)


def remove_governed_concepts_folder(root: Path) -> None:
    for folder in load_entity_catalog().folder_types:
        (root / "wiki" / folder).mkdir(exist_ok=True)
    shutil.rmtree(root / "wiki" / "concepts")
    edit(root, "wiki/domain.md", "status: unconfigured", "status: configured")


run_case(
    "configured-layout-drift-fails-tier1",
    remove_governed_concepts_folder,
    expect_code=1,
    expect=("entity-configuration", "governed entity folders missing: concepts"),
)
# ---- Tier 1: meta-page dangling links (promoted from Tier-2; gates commit) ----
run_case(
    "meta-dangling-link-fires",
    lambda r: append(r, "wiki/index.md", "\nSee [[no-such-meta-target]] for details.\n"),
    expect_code=1, expect=("meta-dangling-link", "index.md: [[no-such-meta-target]]"),
)
run_case(
    "meta-dangling-ignores-folder-and-code",
    lambda r: append(r, "wiki/index.md", "\nRouting: [[concepts/]]. Example: `[[demo]]`.\n"),
    expect_code=0, absent=("index.md: [[concepts/]]", "index.md: [[demo]]"),
)
run_case(
    # content:links#3: an in-code-span [[link]] on a META page must not fire
    # even when its target is a real-looking but nonexistent slug.
    "meta-dangling-in-code-span-ignored",
    lambda r: append(r, "wiki/index.md",
                     "\nSyntax example: `[[some-undefined-meta-demo]]`.\n"),
    expect_code=0, absent=("some-undefined-meta-demo",),
)
run_case(
    "meta-dangling-rich-code-ignored",
    lambda r: append(
        r,
        "wiki/index.md",
        "\nDouble ``[[double-meta-decoy]]``.\n"
        "~~~\n[[tilde-meta-decoy]]\n~~~\n"
        "````python\n``` inner literal\n[[four-meta-decoy]]\n````\n",
    ),
    expect_code=0,
    absent=("double-meta-decoy", "tilde-meta-decoy", "four-meta-decoy"),
)

# ---- Phase 5: fail-closed structure and governed Tier-1 data ----
run_case(
    "direct-entity-junk-file-fails",
    lambda r: (r / "wiki/concepts/illegal.bin").write_bytes(b"junk"),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/illegal.bin", "non-.md"),
    absent=("Traceback",),
)
run_case(
    "empty-direct-entity-directory-fails",
    lambda r: (r / "wiki/concepts/nested").mkdir(),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/nested", "directory"),
    absent=("Traceback",),
)
run_case(
    "direct-entity-broken-symlink-fails",
    lambda r: (r / "wiki/concepts/escape.md").symlink_to(r / "missing-target.md"),
    args=(),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/escape.md", "special entry"),
    absent=("Traceback",),
)
run_case(
    "direct-entity-directory-symlink-fails",
    lambda r: (r / "wiki/concepts/directory-link.md").symlink_to(
        r / "wiki/concepts", target_is_directory=True
    ),
    args=(),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/directory-link.md", "special entry"),
    absent=("Traceback",),
)

for case_name, registry, marker in (
    ("raw-buckets-list-top-level-fails", [], "top level must be a JSON object"),
    ("raw-buckets-empty-object-fails", {}, "nonempty string 'description'"),
    (
        "raw-buckets-empty-buckets-fails",
        {"description": "fixture", "buckets": {}},
        "'buckets' must be a nonempty object",
    ),
    (
        "raw-buckets-bad-key-fails",
        {"description": "fixture", "buckets": {"Bad Bucket": "fixture"}},
        "bucket key 'Bad Bucket' is not kebab-case",
    ),
    (
        "raw-buckets-blank-description-fails",
        {"description": "  ", "buckets": {"notes": "fixture"}},
        "nonempty string 'description'",
    ),
    (
        "raw-buckets-blank-bucket-description-fails",
        {"description": "fixture", "buckets": {"notes": "  "}},
        "bucket 'notes' needs a nonempty string description",
    ),
):
    run_case(
        case_name,
        lambda r, value=registry: write_raw_buckets(r, value),
        expect_code=1,
        expect=("raw-buckets", marker),
        absent=("Traceback",),
    )

for page, field in (
    ("wiki/concepts/alpha.md", "title"),
    ("wiki/concepts/alpha.md", "type"),
    ("wiki/concepts/alpha.md", "created"),
    ("wiki/concepts/alpha.md", "updated"),
    ("wiki/concepts/alpha.md", "confidence"),
    ("wiki/sources/gamma.md", "source_type"),
):
    for suffix, replacement in (("blank", ""), ("quote-only", "''")):
        run_case(
            f"required-{field}-{suffix}-fails",
            lambda r, rel=page, key=field, value=replacement: edit(
                r, rel, next(
                    line for line in (r / rel).read_text().splitlines()
                    if line.startswith(f"{key}:")
                ), f"{key}: {value}"
            ),
            expect_code=1,
            expect=("frontmatter", f"{field} must be a nonempty scalar"),
            absent=("Traceback",),
        )

for meta_name in sorted(META_PAGES):
    run_case(
        f"non-utf8-meta-{meta_name.lower()}-fails-cleanly",
        lambda r, name=meta_name: (r / "wiki" / f"{name}.md").write_bytes(b"\xff"),
        expect_code=1,
        expect=("meta-encoding", f"wiki/{meta_name}.md", "not valid UTF-8"),
        absent=("Traceback",),
    )

run_case(
    "sourcing-marker-duplicate-attribute-fails",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts folder=sources count=5 -->"
    ),
    expect_code=1,
    expect=("sourcing-queue-count-marker", "duplicate attribute 'folder'"),
    absent=("Traceback",),
)
run_case(
    "sourcing-marker-unknown-attribute-fails",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts count=5 extra=yes -->"
    ),
    expect_code=1,
    expect=("sourcing-queue-count-marker", "unknown attribute 'extra'"),
    absent=("Traceback",),
)
run_case(
    "sourcing-marker-unparsed-attribute-text-fails",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts stray count=5 -->"
    ),
    expect_code=1,
    expect=("sourcing-queue-count-marker", "malformed attribute text"),
    absent=("Traceback",),
)

LONG_QUOTE_PREFIX = (
    "This deliberately long shared quote prefix contains enough normalized words "
    "and characters to extend well beyond the former eighty character identity boundary"
)
LONG_QUOTE_ONE = LONG_QUOTE_PREFIX + " before ending with the first distinct conclusion."
LONG_QUOTE_TWO = LONG_QUOTE_PREFIX + " before ending with the second distinct conclusion."


def seed_long_quote_identity(root):
    edit(
        root,
        "wiki/concepts/beta.md",
        "Beta body text for the lint eval fixture.",
        f'Beta body text for the lint eval fixture. "{LONG_QUOTE_ONE}" '
        f'(source: [[gamma]])\n\n"{LONG_QUOTE_TWO}" (source: [[gamma]])',
    )
    write_adjudications(root, reviewed_quotes=[{
        "page": "concepts/beta.md",
        "quote": LONG_QUOTE_ONE,
        "reason": "fixture full-identity suppression",
        "date": "2026-07-11",
    }])


run_case(
    "long-quotes-sharing-eighty-character-prefix-stay-distinct",
    seed_long_quote_identity,
    args=(),
    expect_code=0,
    expect=(
        "quote mismatches (quoted text not verbatim in cited source): 1",
        "adjudicated, suppressed via scripts/lint-adjudications.json: 1",
    ),
    absent=("adjudication_dead", "Traceback"),
)


def _install_raw_git_fixture(root: Path, real_git: str) -> bytes:
    """Install one valid local-only raw record and the real pre-commit guard."""
    copy_fixture(root)
    shutil.copyfile(REPO_ROOT / ".gitignore", root / ".gitignore")
    (root / "scripts/hooks").mkdir()
    for name in (
        "wiki_transactions.py", "_file_transactions.py",
        "_transaction_contract.py", "_durable_files.py",
        "wiki_provenance.py", "wiki_lint_frontmatter.py",
        "wiki_lint_contract.py", "wiki_entity_catalog.py",
        "wiki_schema_vocabularies.py",
        "_wiki_parse.py", "_repo_paths.py",
    ):
        shutil.copyfile(REPO_ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copyfile(
        REPO_ROOT / "scripts/entity-catalog.json",
        root / "scripts/entity-catalog.json",
    )
    shutil.copyfile(
        REPO_ROOT / "scripts/schema-vocabularies.json",
        root / "scripts/schema-vocabularies.json",
    )
    shutil.copyfile(
        REPO_ROOT / "scripts/hooks/pre-commit", root / "scripts/hooks/pre-commit"
    )
    source = root / "raw/notes/source.txt"
    source.parent.mkdir(parents=True)
    (source.parent / ".gitkeep").write_text("", encoding="utf-8")
    source_bytes = b"local source artifact\n"
    source.write_bytes(source_bytes)
    (root / "wiki/sources/tracked-source.md").write_text(
        "---\ntitle: Tracked source\ntype: source\n"
        "created: 2026-08-22\nupdated: 2026-08-22\n"
        "sources: [\"raw/notes/source.txt\"]\ntags: [fixture]\n"
        "confidence: high\nsource_type: other\n"
        "agent_use_cases:\n  - raw privacy eval\n---\n\nTracked source.\n",
        encoding="utf-8",
    )
    append(
        root, "wiki/index.md",
        "| [tracked-source.md](sources/tracked-source.md) | Tracked source fixture |\n",
    )
    (root / "scripts/raw-artifacts.json").write_text(
        json.dumps({
            "artifacts": [{
                "captured_at": "2026-08-22",
                "files": [{
                    "path": "raw/notes/source.txt",
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "size": len(source_bytes),
                }],
                "source_slug": "tracked-source",
            }],
            "schema_version": 1,
        }, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    subprocess.run([real_git, "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [real_git, "config", "user.email", "eval@example.invalid"],
        cwd=root, check=True, capture_output=True,
    )
    subprocess.run(
        [real_git, "config", "user.name", "Wiki Eval"],
        cwd=root, check=True, capture_output=True,
    )
    return source_bytes


def check_untracked_raw_artifact_workflow_passes():
    """Local raw bytes pass lint and the hook while remaining outside Git."""
    real_git = shutil.which("git")
    if real_git is None:
        fail_prerequisite(
            "untracked-raw-artifact-workflow-passes", "git prerequisite unavailable"
        )
        return
    with tempfile.TemporaryDirectory(prefix="wiki-raw-tracking-") as td:
        root = Path(td)
        _install_raw_git_fixture(root, real_git)
        add = subprocess.run(
            [real_git, "add", "-A"], cwd=root, text=True, capture_output=True
        )
        subprocess.run(
            [real_git, "commit", "-qm", "fixture"],
            cwd=root, check=True, capture_output=True,
        )
        tracked = subprocess.run(
            [real_git, "ls-files", "--error-unmatch", "raw/notes/source.txt"],
            cwd=root, text=True, capture_output=True,
        )
        lint = subprocess.run(
            [sys.executable, str(LINT), "--tier1"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        hook = subprocess.run(
            ["sh", "scripts/hooks/pre-commit"],
            cwd=root, text=True, capture_output=True,
        )
        ok = (
            add.returncode == 0
            and tracked.returncode != 0
            and lint.returncode == 0
            and hook.returncode == 0
        )
        name = "untracked-raw-artifact-workflow-passes"
        results.append((name, ok))
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            print(
                f"  add={add.returncode} tracked={tracked.returncode} "
                f"lint={lint.returncode} hook={hook.returncode}; "
                f"stderr={(add.stderr + tracked.stderr + lint.stderr + hook.stderr)[:500]}"
            )


def check_tracked_raw_artifact_fires():
    """A forced raw artifact addition fails the Tier-1 privacy guard."""
    real_git = shutil.which("git")
    if real_git is None:
        fail_prerequisite("tracked-raw-artifact-fires", "git prerequisite unavailable")
        return
    with tempfile.TemporaryDirectory(prefix="wiki-raw-leak-") as td:
        root = Path(td)
        _install_raw_git_fixture(root, real_git)
        subprocess.run(
            [real_git, "add", "-A"], cwd=root, check=True, capture_output=True
        )
        subprocess.run(
            [real_git, "add", "-f", "raw/notes/source.txt"],
            cwd=root, check=True, capture_output=True,
        )
        proc = subprocess.run(
            [sys.executable, str(LINT), "--tier1"],
            cwd=root, text=True, capture_output=True,
        )
        output = proc.stdout + proc.stderr
        ok = proc.returncode == 1 and "raw-tracked" in output and "source.txt" in output
        name = "tracked-raw-artifact-fires"
        results.append((name, ok))
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            print(f"  exit {proc.returncode}; output: {output[:500]}")


def check_tracked_raw_case_variant_fires():
    """The privacy guard catches case variants even on case-tolerant Git setups."""
    real_git = shutil.which("git")
    if real_git is None:
        fail_prerequisite("tracked-raw-case-variant-fires", "git prerequisite unavailable")
        return
    with tempfile.TemporaryDirectory(prefix="wiki-raw-case-") as td:
        root = Path(td)
        copy_fixture(root)
        subprocess.run([real_git, "init", "-q"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            [real_git, "config", "core.ignorecase", "true"],
            cwd=root, check=True, capture_output=True,
        )
        (root / "Raw").mkdir()
        (root / "Raw/leak.txt").write_text("secret", encoding="utf-8")
        subprocess.run(
            [real_git, "add", "-f", "Raw/leak.txt"],
            cwd=root, check=True, capture_output=True,
        )
        proc = subprocess.run(
            [sys.executable, str(LINT), "--tier1"],
            cwd=root, text=True, capture_output=True,
        )
        output = proc.stdout + proc.stderr
        ok = proc.returncode == 1 and "raw-tracked" in output and "Raw/leak.txt" in output
        name = "tracked-raw-case-variant-fires"
        results.append((name, ok))
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            print(f"  exit {proc.returncode}; output: {output[:500]}")


def check_git_tracking_query_failure_fires():
    """A failed Git tracking query cannot be reported as clean inside a worktree."""
    real_git = shutil.which("git")
    if real_git is None:
        fail_prerequisite("git-tracking-query-failure-fires", "git prerequisite unavailable")
        return
    with tempfile.TemporaryDirectory(prefix="wiki-git-query-") as td:
        root = Path(td)
        copy_fixture(root)
        subprocess.run([real_git, "init", "-q"], cwd=root, check=True, capture_output=True)
        fake_bin = root / "tmp/fake-bin"
        fake_bin.mkdir(parents=True)
        fake_git = fake_bin / "git"
        fake_git.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"rev-parse\" ]; then echo true; exit 0; fi\n"
            "if [ \"$1\" = \"ls-files\" ]; then echo forced failure >&2; exit 73; fi\n"
            f'exec "{real_git}" "$@"\n',
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            [sys.executable, str(LINT), "--tier1"],
            cwd=root, text=True, capture_output=True, env=env,
        )
        output = proc.stdout + proc.stderr
        ok = (
            proc.returncode == 1
            and "raw-tracked" in output
            and "forced failure" in output
            and "Traceback" not in output
        )
        name = "git-tracking-query-failure-fires"
        results.append((name, ok))
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            print(f"  exit {proc.returncode}; output: {output[:500]}")


check_untracked_raw_artifact_workflow_passes()
check_tracked_raw_artifact_fires()
check_tracked_raw_case_variant_fires()
check_git_tracking_query_failure_fires()

raise SystemExit(finish_lint_eval())
