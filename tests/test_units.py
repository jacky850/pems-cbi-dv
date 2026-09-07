"""Legacy aliases equal their canonical columns, and units are what they claim.

`D_counts` and `D_speed` are congested-bin passed volumes in vehicles. They are
not the rate-based demand D in D/C. `DC_hours` is a duration in hours, not a
dimensionless ratio. The names said otherwise, so they are moving; these tests
hold the old and new columns to identical values for the one release they
overlap.

See DATA_DICTIONARY.md and the canonical variable contract.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "outputs/pems_cbi_link_period.csv"

# legacy name -> canonical name. Removed in v0.4.
ALIASES = {
    "D_counts": "congested_passed_volume_counts_veh",
    "D_speed": "congested_passed_volume_speed_veh",
    "DC_hours": "capacity_equivalent_hours_counts",
    "V_counts": "period_volume_counts_veh",
    "V_speed": "period_volume_speed_veh",
}

UNITS = {
    "congested_passed_volume_counts_veh": "veh",
    "congested_passed_volume_speed_veh": "veh",
    "period_volume_counts_veh": "veh",
    "period_volume_speed_veh": "veh",
    "capacity_equivalent_hours_counts": "h",
}


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    if not TABLE.exists():
        pytest.skip("run `python -m pems_cbi.run table` first")
    return pd.read_csv(TABLE)


@pytest.mark.parametrize("legacy,canonical", sorted(ALIASES.items()))
def test_alias_equals_canonical(table, legacy, canonical):
    assert legacy in table, f"{legacy} was dropped before v0.4"
    assert canonical in table, f"{canonical} is missing"
    assert table[legacy].to_numpy() == pytest.approx(
        table[canonical].to_numpy(), nan_ok=True), (
        f"{legacy} and {canonical} must carry identical values in v0.3")


def test_capacity_equivalent_hours_is_a_duration(table):
    """Vehicles over an hourly rate. Reconstruct it and check the units line up."""
    reconstructed = table["congested_passed_volume_counts_veh"] / table["capacity_vph"]
    assert table["capacity_equivalent_hours_counts"].to_numpy() == pytest.approx(
        reconstructed.to_numpy(), nan_ok=True)
    assert UNITS["capacity_equivalent_hours_counts"] == "h"


def test_capacity_equivalent_hours_is_not_a_ratio(table):
    """A dimensionless v/c would sit near 1. This is a duration and does not.

    The point of the rename: on an 11-hour NT period this reaches several hours,
    which is nonsense read as a ratio and correct read as a duration.
    """
    hours = table["capacity_equivalent_hours_counts"].dropna()
    assert hours.max() > 1.5, (
        "if every value were below 1.5 the column would be indistinguishable "
        "from a v/c ratio and this test could not tell them apart")
    congested = table.loc[table["bins_below_cutoff"] > 0, "capacity_equivalent_hours_counts"]
    period_hours = table.loc[table["bins_below_cutoff"] > 0, "bins"] * 5 / 60
    assert (congested <= period_hours + 1e-9).all(), (
        "clearing at capacity cannot take longer than the period the vehicles "
        "were counted in")


def test_congested_volume_never_exceeds_period_volume(table):
    """D sums a subset of the bins V sums, on the same flow series."""
    for congested, whole in [("congested_passed_volume_counts_veh", "period_volume_counts_veh"),
                             ("congested_passed_volume_speed_veh", "period_volume_speed_veh")]:
        assert (table[congested] <= table[whole] + 1e-6).all(), (
            f"{congested} exceeds {whole}, so it is not summing a subset of the bins")


def test_uncongested_rows_carry_zero_congested_volume(table):
    quiet = table[table["bins_below_cutoff"] == 0]
    assert (quiet["congested_passed_volume_counts_veh"] == 0).all()
    assert (quiet["capacity_equivalent_hours_counts"] == 0).all()


def test_evidence_layers_are_declared(table):
    """Counted and speed-inferred quantities are not the same evidence."""
    assert set(table["counts_evidence_layer"].unique()) == {"A_OBSERVED"}
    assert set(table["speed_evidence_layer"].unique()) == {"B_RECOVERED"}
    assert set(table["schema_version"].astype(str).unique()) == {"0.3"}


def test_speed_inferred_columns_are_not_labelled_observed(table):
    """Layer B is model-informed recovery. Calling it observed is the error the
    contract exists to prevent."""
    assert table["speed_evidence_layer"].iloc[0] != "A_OBSERVED"
