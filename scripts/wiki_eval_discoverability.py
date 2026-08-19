#!/usr/bin/env python3
"""Acceptance controls for production discoverability classification."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_lib import Results


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import check_discoverability as discoverability  # noqa: E402

sys.path.pop(0)


def findings_of_kind(
    report: discoverability.DiscoverabilityReport,
    kind: str,
) -> list[discoverability.Finding]:
    """Return production blockers matching ``kind``."""
    return [
        finding
        for finding in report["production_blockers"]
        if finding["kind"] == kind
    ]


def main() -> int:
    """Exercise live and isolated discoverability contracts."""
    results = Results()

    live_report = discoverability.collect_discoverability_report(REPO_ROOT)
    results.record(
        "live-production-discoverability-is-clean",
        not live_report["production_blockers"],
        json.dumps(live_report["production_blockers"], sort_keys=True),
    )
    results.record(
        "known-miniature-wiki-index-is-allowed-not-suppressed",
        live_report["allowed_fixture_names"]
        == [
            {
                "kind": "allowed-fixture-name",
                "line": 0,
                "path": "scripts/fixtures/wiki-lint/wiki/index.md",
                "symbol": "index.md",
            }
        ],
        json.dumps(live_report["allowed_fixture_names"], sort_keys=True),
    )

    with tempfile.TemporaryDirectory(prefix="wiki-discoverability-") as temp_directory:
        root = Path(temp_directory)
        scripts_dir = root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "generic_fixture.py").write_text(
            "def run(value):\n"
            "    return value\n",
            encoding="utf-8",
        )
        (scripts_dir / "review_due.py").write_text(
            "def collect(root: str) -> list[str]:\n"
            "    return []\n",
            encoding="utf-8",
        )
        (scripts_dir / "lint_contract.py").write_text(
            "class PageContext:\n"
            "    def __init__(self, path):\n"
            "        self.path = path\n"
            "\n"
            "__all__ = ['PageContext']\n",
            encoding="utf-8",
        )
        (scripts_dir / "implicit_contract.py").write_text(
            "class ImplicitPageContext:\n"
            "    def __init__(self, path):\n"
            "        self.path = path\n",
            encoding="utf-8",
        )
        (scripts_dir / "interface_owner.py").write_text(
            "def exported_name(value: str) -> str:\n"
            "    return value\n"
            "\n"
            "def collect(value: str) -> str:\n"
            "    return value\n"
            "\n"
            "__all__ = ['exported_name']\n",
            encoding="utf-8",
        )
        (scripts_dir / "interface_consumer.py").write_text(
            "from interface_owner import collect\n"
            "\n"
            "def use_hidden_collection(value: str) -> str:\n"
            "    return collect(value)\n",
            encoding="utf-8",
        )
        (scripts_dir / "interface_qualified_consumer.py").write_text(
            "import interface_owner as owner\n"
            "\n"
            "def use_qualified_hidden_collection(value: str) -> str:\n"
            "    return owner.collect(value)\n",
            encoding="utf-8",
        )
        fixture_index = scripts_dir / "fixtures" / "wiki-lint" / "wiki" / "index.md"
        fixture_index.parent.mkdir(parents=True)
        fixture_index.write_text("# Miniature index\n", encoding="utf-8")
        report_path = root / "tmp" / "discoverability.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "check_discoverability.py"),
                "--repo",
                str(root),
                "--report",
                str(report_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        report: discoverability.DiscoverabilityReport = json.loads(
            report_path.read_text(encoding="utf-8")
        )
        results.record(
            "isolated-untyped-generic-production-fixture-fails",
            result.returncode == 1
            and bool(findings_of_kind(report, "generic-callable"))
            and bool(findings_of_kind(report, "incomplete-public-signature")),
            f"returncode={result.returncode} report={json.dumps(report, sort_keys=True)}",
        )
        results.record(
            "isolated-generic-collection-interface-fails",
            any(
                finding["symbol"] == "collect"
                for finding in findings_of_kind(report, "generic-callable")
            ),
            json.dumps(report, sort_keys=True),
        )
        results.record(
            "isolated-untyped-exported-constructor-fails",
            any(
                str(finding["symbol"]).startswith("PageContext.__init__")
                for finding in findings_of_kind(report, "incomplete-public-signature")
            ),
            json.dumps(report, sort_keys=True),
        )
        results.record(
            "isolated-untyped-implicit-public-constructor-fails",
            any(
                str(finding["symbol"]).startswith("ImplicitPageContext.__init__")
                for finding in findings_of_kind(report, "incomplete-public-signature")
            ),
            json.dumps(report, sort_keys=True),
        )
        results.record(
            "isolated-import-omitted-from-declared-interface-fails",
            any(
                finding["symbol"] == "interface_owner.collect"
                for finding in findings_of_kind(report, "import-not-exported")
            ),
            json.dumps(report, sort_keys=True),
        )
        results.record(
            "isolated-qualified-import-omitted-from-declared-interface-fails",
            any(
                finding["path"] == "scripts/interface_qualified_consumer.py"
                and finding["symbol"] == "interface_owner.collect"
                for finding in findings_of_kind(report, "import-not-exported")
            ),
            json.dumps(report, sort_keys=True),
        )
        results.record(
            "isolated-index-fixture-is-allowed-without-global-index-suppression",
            report["allowed_fixture_names"]
            == [
                {
                    "kind": "allowed-fixture-name",
                    "line": 0,
                    "path": "scripts/fixtures/wiki-lint/wiki/index.md",
                    "symbol": "index.md",
                }
            ]
            and not report["fixture_test_observations"],
            json.dumps(report, sort_keys=True),
        )

    return results.finish()


if __name__ == "__main__":
    raise SystemExit(main())
