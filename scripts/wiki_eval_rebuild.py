#!/usr/bin/env python3
"""Regression eval for rebuild_referenced_by.py.

Guards the two invariants of the generated inbound-link graph:

1. Only authored links count. A one-way authored link must never become a
   two-way edge by way of a previously generated "## Referenced by" block
   (the fixture seeds a poisoned block and expects it cleaned).
2. Idempotency. A second rebuild over already-correct pages is a byte-level
   no-op.

Runs against the fixture mini-wiki in scripts/fixtures/wiki-rebuild/, copied
into a system temp directory. Writes nothing inside the repo.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import rebuild_referenced_by as rebuild
from eval_lib import Results
from _wiki_parse import get_entity_pages

REPO_ROOT = Path(__file__).resolve().parents[1]
REBUILD_SCRIPT = REPO_ROOT / "scripts" / "rebuild_referenced_by.py"
FIXTURE_WIKI = REPO_ROOT / "scripts" / "fixtures" / "wiki-rebuild" / "wiki"

SECTION_RE = re.compile(r"## Referenced by\n.*?(?=\n## |\Z)", re.DOTALL)


def read_tree(root: Path) -> dict:
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.md"))
    }


def read_tree_bytes(root: Path) -> dict[str, bytes]:
    """Snapshot every file so a failed rebuild cannot hide partial writes."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def referenced_by_section(text: str) -> str:
    m = SECTION_RE.search(text)
    return m.group(0) if m else ""


def main() -> int:
    results = Results()
    check = results.record

    tmp = Path(tempfile.mkdtemp(prefix="wiki-rebuild-eval-"))
    try:
        help_case = tmp / "help"
        shutil.copytree(FIXTURE_WIKI, help_case / "wiki")
        help_before = read_tree_bytes(help_case / "wiki")
        help_run = subprocess.run(
            [sys.executable, str(REBUILD_SCRIPT), "--help"],
            cwd=help_case,
            capture_output=True,
            text=True,
        )
        check(
            "help-is-read-only",
            help_run.returncode == 0
            and "usage:" in help_run.stdout.lower()
            and read_tree_bytes(help_case / "wiki") == help_before,
            help_run.stderr.strip(),
        )
        unknown_run = subprocess.run(
            [sys.executable, str(REBUILD_SCRIPT), "--unknown-option"],
            cwd=help_case,
            capture_output=True,
            text=True,
        )
        check(
            "unknown-option-is-rejected-without-writing",
            unknown_run.returncode == 2
            and read_tree_bytes(help_case / "wiki") == help_before,
            unknown_run.stderr.strip(),
        )

        invalid_case = tmp / "invalid-utf8"
        shutil.copytree(FIXTURE_WIKI, invalid_case / "wiki")
        invalid_page = invalid_case / "wiki" / "sources" / "zz-invalid.md"
        invalid_page.write_bytes(b"# Late invalid page\n\n\xff\n")
        before_invalid = read_tree_bytes(invalid_case / "wiki")
        invalid_run = subprocess.run(
            [sys.executable, str(REBUILD_SCRIPT)],
            cwd=invalid_case,
            capture_output=True,
            text=True,
        )
        after_invalid = read_tree_bytes(invalid_case / "wiki")
        check(
            "invalid-utf8-fails-cleanly",
            invalid_run.returncode != 0
            and "zz-invalid.md" in invalid_run.stderr
            and "Traceback" not in invalid_run.stderr,
            invalid_run.stderr.strip(),
        )
        all_invalid_paths = set(before_invalid) | set(after_invalid)
        changed_invalid = sorted(
            path
            for path in all_invalid_paths
            if before_invalid.get(path) != after_invalid.get(path)
        )
        check(
            "invalid-utf8-preserves-entire-tree",
            before_invalid == after_invalid,
            f"files changed before the late read failure: {changed_invalid}",
        )

        write_failure_case = tmp / "write-failure"
        shutil.copytree(FIXTURE_WIKI, write_failure_case / "wiki")
        read_only_page = write_failure_case / "wiki" / "concepts" / "alpha.md"
        read_only_page.chmod(0o444)
        try:
            write_failure_run = subprocess.run(
                [sys.executable, str(REBUILD_SCRIPT)],
                cwd=write_failure_case,
                capture_output=True,
                text=True,
            )
        finally:
            read_only_page.chmod(0o644)
        check(
            "low-level-write-failure-is-nonzero",
            write_failure_run.returncode != 0
            and "cannot write wiki/concepts/alpha.md" in write_failure_run.stderr
            and "Traceback" not in write_failure_run.stderr,
            write_failure_run.stderr.strip(),
        )

        shutil.copytree(FIXTURE_WIKI, tmp / "wiki")
        run = lambda: subprocess.run(
            [sys.executable, str(REBUILD_SCRIPT)],
            cwd=tmp,
            capture_output=True,
            text=True,
        )

        first = run()
        check("first-rebuild-exits-zero", first.returncode == 0, first.stderr.strip())
        after_first = read_tree(tmp / "wiki")

        alpha = after_first.get("concepts/alpha.md", "")
        beta = after_first.get("concepts/beta.md", "")
        delta = after_first.get("concepts/delta.md", "")
        gamma = after_first.get("sources/gamma.md", "")

        alpha_sec = referenced_by_section(alpha)
        check(
            "phantom-edge-removed",
            "[[beta]]" not in alpha_sec,
            "alpha's seeded poisoned block survived: one-way link became two-way",
        )
        check(
            "authored-inbound-kept",
            "[[gamma]]" in alpha_sec and "[[delta]]" in alpha_sec,
            f"alpha section: {alpha_sec!r}",
        )
        check(
            "stale-section-refreshed",
            "[[alpha]]" in referenced_by_section(beta),
            "beta's stale 'no inbound' block was not refreshed",
        )
        check(
            "no-inbound-marker",
            "_No inbound links yet._" in referenced_by_section(gamma),
            f"gamma section: {referenced_by_section(gamma)!r}",
        )
        check(
            "insertion-before-related",
            "## Referenced by" in gamma
            and gamma.index("## Referenced by") < gamma.index("## Related pages"),
            "gamma's new section was not inserted before Related pages",
        )
        check(
            "byte0-related-prepended",
            delta.startswith("## Referenced by"),
            "delta (file starting with '## Related pages') was not prepended",
        )

        # mtimes, not just bytes: byte comparison alone cannot distinguish the
        # skip-unchanged write path from rewriting identical content, which
        # churns every page's mtime on every rebuild.
        mtimes_before = {
            k: (tmp / "wiki" / k).stat().st_mtime_ns for k in after_first
        }
        second = run()
        check("second-rebuild-exits-zero", second.returncode == 0, second.stderr.strip())
        after_second = read_tree(tmp / "wiki")
        changed = sorted(
            k for k in after_first if after_first[k] != after_second.get(k)
        )
        check(
            "idempotent-second-pass",
            after_first == after_second,
            f"files changed on second rebuild: {changed}",
        )
        mtimes_after = {
            k: (tmp / "wiki" / k).stat().st_mtime_ns for k in after_first
        }
        check(
            "second-pass-rewrites-nothing",
            mtimes_before == mtimes_after,
            "already-correct pages were rewritten byte-identically (mtime churn): "
            + ", ".join(sorted(k for k in mtimes_before
                               if mtimes_before[k] != mtimes_after.get(k))),
        )

        # A [[link]] inside a code fence is a syntax example, not an authored
        # edge: adding a fenced [[gamma]] to beta must NOT give gamma an inbound
        # entry (the same strip_code_spans rule lint's scans apply).
        beta_path = tmp / "wiki" / "concepts" / "beta.md"
        beta_path.write_text(
            beta_path.read_text()
            + "\n```\nSyntax example: [[gamma]] inside a fence.\n```\n"
        )
        fence_run = run()
        gamma_after = (tmp / "wiki" / "sources" / "gamma.md").read_text()
        check(
            "code-fence-link-not-counted",
            fence_run.returncode == 0
            and "_No inbound links yet._" in referenced_by_section(gamma_after),
            f"gamma section after fenced link: {referenced_by_section(gamma_after)!r}",
        )

        # A fenced "## Referenced by" example documenting the convention is
        # authored content, not the generated section: the rebuild must leave
        # it byte-identical and maintain the real section around it.
        beta_path = tmp / "wiki" / "concepts" / "beta.md"
        fenced_example = ("\n```markdown\n## Referenced by\n\n"
                         "**concepts/**  [[example]]\n```\n")
        beta_path.write_text(beta_path.read_text() + fenced_example)
        fence_write_run = run()
        beta_after = beta_path.read_text()
        check(
            "fenced-section-example-preserved",
            fence_write_run.returncode == 0 and fenced_example in beta_after
            and "[[alpha]]" in referenced_by_section(beta_after),
            "a fenced '## Referenced by' example was rewritten or the real "
            "section was lost",
        )

        # Scan side of the same fence rule (composition order: fences are
        # blanked BEFORE the generated-section strip). A fenced "## Referenced
        # by" example must not start a section strip that eats its own closing
        # fence and the authored links after it: the fenced [[delta]] must not
        # leak an inbound edge, and the post-fence [[gamma]] must still count.
        epsilon_path = tmp / "wiki" / "concepts" / "epsilon.md"
        epsilon_path.write_text(
            "# Epsilon\n\nDocumenting the convention:\n"
            "\n```markdown\n## Referenced by\n\n**concepts/**  [[delta]]\n```\n"
            "\nAuthored prose referencing [[gamma]].\n"
        )
        scan_run = run()
        gamma_scan = (tmp / "wiki" / "sources" / "gamma.md").read_text()
        delta_scan = (tmp / "wiki" / "concepts" / "delta.md").read_text()
        check(
            "post-fence-authored-link-counts",
            scan_run.returncode == 0
            and "[[epsilon]]" in referenced_by_section(gamma_scan),
            f"gamma section: {referenced_by_section(gamma_scan)!r}",
        )
        check(
            "fenced-example-link-does-not-leak-inbound",
            "[[epsilon]]" not in referenced_by_section(delta_scan),
            f"delta section: {referenced_by_section(delta_scan)!r}",
        )

        # last (it mutates state): a hand edit that duplicated the generated
        # section must collapse back to exactly one
        alpha_path = tmp / "wiki" / "concepts" / "alpha.md"
        alpha_path.write_text(
            alpha_path.read_text() + "\n## Referenced by\n\nstale duplicate\n"
        )
        dup_run = run()
        collapsed = alpha_path.read_text()
        check(
            "duplicate-sections-collapsed",
            dup_run.returncode == 0 and collapsed.count("## Referenced by") == 1,
            f"{collapsed.count('## Referenced by')} sections remain after rebuild",
        )

        interrupted_case = tmp / "interrupted-rerun"
        shutil.copytree(FIXTURE_WIKI, interrupted_case / "wiki")
        pages = get_entity_pages(interrupted_case / "wiki")
        snapshot = rebuild.load_page_texts(pages)
        changed, _counts = rebuild.build_backlink_rebuild_plan(
            snapshot, interrupted_case / "wiki"
        )
        try:
            rebuild.apply_backlink_rebuild_plan(
                changed,
                snapshot,
                repo_root=interrupted_case,
                fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
                if event == "after_page:1" else None,
            )
        except RuntimeError:
            faulted = True
        else:
            faulted = False
        rerun = subprocess.run(
            [sys.executable, str(REBUILD_SCRIPT)],
            cwd=interrupted_case,
            capture_output=True,
            text=True,
        )
        final_snapshot = rebuild.load_page_texts(get_entity_pages(interrupted_case / "wiki"))
        remaining, _counts = rebuild.build_backlink_rebuild_plan(
            final_snapshot, interrupted_case / "wiki"
        )
        check(
            "interrupted-rebuild-rerun-converges",
            faulted and rerun.returncode == 0 and not remaining,
            rerun.stdout + rerun.stderr,
        )

        conflict_case = tmp / "transaction-conflict"
        shutil.copytree(FIXTURE_WIKI, conflict_case / "wiki")
        pages = get_entity_pages(conflict_case / "wiki")
        snapshot = rebuild.load_page_texts(pages)
        changed, _counts = rebuild.build_backlink_rebuild_plan(snapshot, conflict_case / "wiki")
        late_page = sorted(changed)[-1]
        third_party = b"third-party authored edit\n"

        def concurrent_edit(event: str) -> None:
            if event == "after_page:0":
                late_page.write_bytes(third_party)

        try:
            rebuild.apply_backlink_rebuild_plan(
                changed,
                snapshot,
                repo_root=conflict_case,
                fault=concurrent_edit,
            )
        except rebuild.RebuildError:
            conflicted = True
        else:
            conflicted = False
        check(
            "late-concurrent-page-edit-is-preserved",
            conflicted and late_page.read_bytes() == third_party,
            late_page.read_text(encoding="utf-8"),
        )

        no_op_case = tmp / "transaction-no-op"
        shutil.copytree(FIXTURE_WIKI, no_op_case / "wiki")
        pages = get_entity_pages(no_op_case / "wiki")
        first_snapshot = rebuild.load_page_texts(pages)
        first_changed, _counts = rebuild.build_backlink_rebuild_plan(first_snapshot, no_op_case / "wiki")
        rebuild.apply_backlink_rebuild_plan(first_changed, first_snapshot, repo_root=no_op_case)
        second_snapshot = rebuild.load_page_texts(pages)
        second_changed, _counts = rebuild.build_backlink_rebuild_plan(second_snapshot, no_op_case / "wiki")
        second_recovery = rebuild.apply_backlink_rebuild_plan(second_changed, second_snapshot, repo_root=no_op_case)
        check(
            "no-op-rebuild-creates-no-recovery-state",
            not second_changed and second_recovery == []
            and not (no_op_case / ".wiki-transactions").exists(),
            f"changed={len(second_changed)}",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
