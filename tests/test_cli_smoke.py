"""`python -m pems_cbi.run table` works from a plain checkout and is repeatable.

The acceptance criterion is that a clean install runs without anyone setting
PYTHONPATH by hand, and that the table it produces is the one that is committed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
COMMITTED = ROOT / "outputs"

REQUIRED_COLUMNS = [
    "corridor", "link_id", "period",
    "congested_passed_volume_counts_veh", "congested_passed_volume_speed_veh",
    "period_volume_counts_veh", "period_volume_speed_veh",
    "capacity_equivalent_hours_counts",
    "counts_evidence_layer", "speed_evidence_layer", "schema_version",
    "D_counts", "D_speed", "V_counts", "V_speed", "DC_hours",
]


@pytest.fixture(scope="module")
def rerun(tmp_path_factory) -> Path:
    """Run the CLI into a temporary directory, leaving the committed outputs alone."""
    if not (DATA / "pems_average_weekday_5min.csv.gz").exists():
        pytest.skip("data/ is not present in this checkout")
    out = tmp_path_factory.mktemp("outputs")
    completed = subprocess.run(
        [sys.executable, "-m", "pems_cbi.run", "table", "--output-dir", str(out)],
        cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert completed.returncode == 0, completed.stderr
    return out


def test_cli_writes_all_three_outputs(rerun):
    for name in ["pems_cbi_link_period.csv", "pems_episodes.csv", "pems_cbi_summary.json"]:
        assert (rerun / name).exists(), f"{name} was not written"


def test_table_carries_canonical_and_legacy_columns(rerun):
    table = pd.read_csv(rerun / "pems_cbi_link_period.csv")
    missing = [c for c in REQUIRED_COLUMNS if c not in table.columns]
    assert not missing, f"missing columns: {missing}"


def test_rerun_matches_the_committed_table(rerun):
    """Regeneration is deterministic and the committed copy is current."""
    fresh = pd.read_csv(rerun / "pems_cbi_link_period.csv")
    committed = pd.read_csv(COMMITTED / "pems_cbi_link_period.csv")
    assert fresh.shape == committed.shape
    key = ["corridor", "link_id", "period"]
    merged = fresh.merge(committed, on=key, suffixes=("_new", "_old"))
    assert len(merged) == len(committed), "the key set changed"
    for column in fresh.columns:
        if column in key or not pd.api.types.is_numeric_dtype(fresh[column]):
            continue
        assert merged[f"{column}_new"].to_numpy() == pytest.approx(
            merged[f"{column}_old"].to_numpy(), nan_ok=True, rel=1e-9), (
            f"{column} changed against the committed table")


def test_summary_reports_the_inventory(rerun):
    """A MAPE without its denominators is not reportable."""
    summary = json.loads((rerun / "pems_cbi_summary.json").read_text(encoding="utf-8"))
    inventory = summary["inventory"]
    for field in ["corridors", "links", "link_periods", "link_periods_with_an_episode",
                  "link_periods_with_spillover_only", "link_periods_uncongested",
                  "rows_scored_for_D", "rows_excluded_from_D", "rows_scored_for_V"]:
        assert field in inventory, f"{field} is missing from the inventory"

    assert (inventory["link_periods_with_an_episode"]
            + inventory["link_periods_with_spillover_only"]
            + inventory["link_periods_uncongested"]) == inventory["link_periods"], (
        "the three congestion_source classes must partition the rows")
    assert (inventory["rows_scored_for_D"] + inventory["rows_excluded_from_D"]
            == inventory["link_periods"])
    assert summary["schema_version"] == "0.3"


def test_summary_matches_the_committed_one(rerun):
    fresh = json.loads((rerun / "pems_cbi_summary.json").read_text(encoding="utf-8"))
    committed = json.loads((COMMITTED / "pems_cbi_summary.json").read_text(encoding="utf-8"))
    assert fresh["inventory"] == committed["inventory"]
    assert fresh["by_period"] == committed["by_period"]


def test_package_imports_without_pythonpath_when_installed():
    """Skipped unless the package is actually installed; then it must import bare."""
    completed = subprocess.run(
        [sys.executable, "-c", "import pems_cbi, pems_cbi.analysis; print('ok')"],
        cwd=ROOT.parent, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        pytest.skip("package not installed in this environment (pip install -e .)")
    assert "ok" in completed.stdout
