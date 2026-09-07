"""Check the committed outputs against the schema and against physical sense.

    python scripts/validate_outputs.py

Exits non-zero on any FAIL. Every check prints PASS, FAIL or SKIP with the
number it actually measured, so a green run is evidence rather than an assertion.

This is deliberately separate from the tests: the tests protect the code, this
protects the artefacts a reader will download.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

ALIASES = {
    "D_counts": "congested_passed_volume_counts_veh",
    "D_speed": "congested_passed_volume_speed_veh",
    "DC_hours": "capacity_equivalent_hours_counts",
    "V_counts": "period_volume_counts_veh",
    "V_speed": "period_volume_speed_veh",
}

REQUIRED = [
    "corridor", "link_id", "period", "lanes", "bins", "bins_below_cutoff",
    "free_speed_mph", "speed_at_capacity_mph", "cutoff_mph", "capacity_vph",
    "congestion_source", "P_h", "v_t2_mph", "mu_vph", "mu_over_C",
    *ALIASES.values(), *ALIASES.keys(),
    "counts_evidence_layer", "speed_evidence_layer", "schema_version",
]


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        if not ok:
            self.failures += 1
        print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))

    def skip(self, label: str, why: str) -> None:
        print(f"  [SKIP] {label} — {why}")


def validate_table(table: pd.DataFrame, report: Report) -> None:
    print("\npems_cbi_link_period.csv")

    missing = [c for c in REQUIRED if c not in table.columns]
    report.check(not missing, "every required column is present",
                 f"missing {missing}" if missing else f"{len(table.columns)} columns")

    key = ["corridor", "link_id", "period"]
    duplicated = int(table.duplicated(key).sum())
    report.check(duplicated == 0, "the key is unique", f"{duplicated} duplicate rows")

    for legacy, canonical in sorted(ALIASES.items()):
        if legacy not in table or canonical not in table:
            report.skip(f"{legacy} == {canonical}", "column absent")
            continue
        gap = float(np.nanmax(np.abs(table[legacy] - table[canonical]))) if len(table) else 0.0
        report.check(gap < 1e-9, f"{legacy} == {canonical}", f"worst gap {gap:.3e}")

    if "capacity_equivalent_hours_counts" in table and "capacity_vph" in table:
        rebuilt = table["congested_passed_volume_counts_veh"] / table["capacity_vph"]
        gap = float(np.nanmax(np.abs(table["capacity_equivalent_hours_counts"] - rebuilt)))
        report.check(gap < 1e-9, "capacity_equivalent_hours = congested volume / capacity",
                     f"worst gap {gap:.3e}")

        period_hours = table["bins"] * 5.0 / 60.0
        over = int((table["capacity_equivalent_hours_counts"] > period_hours + 1e-9).sum())
        report.check(over == 0, "clearing time never exceeds the period it was counted in",
                     f"{over} rows over")

    subset = int((table["congested_passed_volume_counts_veh"]
                  > table["period_volume_counts_veh"] + 1e-6).sum())
    report.check(subset == 0, "congested volume <= period volume", f"{subset} rows over")

    negative = int((table[[*ALIASES.values()]] < -1e-9).sum().sum())
    report.check(negative == 0, "no negative volumes or durations", f"{negative} values")

    quiet = table[table["bins_below_cutoff"] == 0]
    zeroed = bool((quiet["congested_passed_volume_counts_veh"] == 0).all())
    report.check(zeroed, "uncongested rows carry zero congested volume",
                 f"{len(quiet)} uncongested rows")

    layers_ok = (set(table["counts_evidence_layer"].unique()) == {"A_OBSERVED"}
                 and set(table["speed_evidence_layer"].unique()) == {"B_RECOVERED"})
    report.check(layers_ok, "evidence layers are declared and correct")

    versions = set(table["schema_version"].astype(str).unique())
    report.check(versions == {"0.3"}, "schema_version is 0.3 on every row", f"{versions}")

    classes = set(table["congestion_source"].unique())
    known = all(c == "own_episode" or c == "none" or c.startswith("spillover_from_")
                for c in classes)
    report.check(known, "congestion_source only takes documented values", f"{sorted(classes)}")

    speeds_ok = bool((table["cutoff_mph"] < table["speed_at_capacity_mph"]).all())
    report.check(speeds_ok, "cut-off sits below the capacity speed",
                 "0.70 v_f < 0.7071 v_f")

    congested = table[table["bins_below_cutoff"] > 0]
    if len(congested):
        deep = int((congested["v_t2_mph"] > congested["cutoff_mph"] + 1e-6).sum())
        report.check(deep == 0, "every episode trough is below its own cut-off",
                     f"{deep} rows above")


def validate_episodes(episodes: pd.DataFrame, report: Report) -> None:
    print("\npems_episodes.csv")
    report.check("wraps_midnight" in episodes, "wraps_midnight is present")

    positive = int((episodes["P_h"] <= 0).sum())
    report.check(positive == 0, "every episode has a positive duration", f"{positive} rows")

    day = int((episodes["P_h"] > 24.0 + 1e-9).sum())
    report.check(day == 0, "no episode is longer than a day", f"{day} rows")

    if "wraps_midnight" in episodes:
        wrapping = episodes[episodes["wraps_midnight"].astype(bool)]
        if len(wrapping):
            ordered = bool((wrapping["t0_min"] > wrapping["t3_min"]).all())
            report.check(ordered, "wrapping episodes start later in the clock than they end",
                         f"{len(wrapping)} wrapping")
        else:
            report.skip("wrapping episode clock order", "no wrapping episodes in this dataset")

    inside = episodes[~episodes.get("wraps_midnight", pd.Series(False, index=episodes.index)).astype(bool)]
    if len(inside):
        ordered = bool((inside["t0_min"] <= inside["T2_min"]).all()
                       and (inside["T2_min"] < inside["t3_min"]).all())
        report.check(ordered, "within-day episodes satisfy t0 <= T2 < t3",
                     f"{len(inside)} rows")


def validate_summary(summary: dict, table: pd.DataFrame, report: Report) -> None:
    print("\npems_cbi_summary.json")
    report.check(summary.get("schema_version") == "0.3", "schema_version is 0.3")

    inventory = summary.get("inventory")
    report.check(inventory is not None, "the inventory block is present")
    if not inventory:
        return

    partition = (inventory["link_periods_with_an_episode"]
                 + inventory["link_periods_with_spillover_only"]
                 + inventory["link_periods_uncongested"])
    report.check(partition == inventory["link_periods"],
                 "congestion classes partition the rows",
                 f"{partition} vs {inventory['link_periods']}")

    scored = inventory["rows_scored_for_D"] + inventory["rows_excluded_from_D"]
    report.check(scored == inventory["link_periods"],
                 "scored plus excluded equals the row count",
                 f"{scored} vs {inventory['link_periods']}")

    report.check(inventory["link_periods"] == len(table),
                 "the inventory row count matches the table", f"{len(table)} rows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()

    table_path = args.output_dir / "pems_cbi_link_period.csv"
    if not table_path.exists():
        print(f"{table_path} does not exist; run `python -m pems_cbi.run table` first")
        return 1

    report = Report()
    table = pd.read_csv(table_path)
    validate_table(table, report)

    episodes_path = args.output_dir / "pems_episodes.csv"
    if episodes_path.exists():
        validate_episodes(pd.read_csv(episodes_path), report)

    summary_path = args.output_dir / "pems_cbi_summary.json"
    if summary_path.exists():
        validate_summary(json.loads(summary_path.read_text(encoding="utf-8")), table, report)

    print()
    if report.failures:
        print(f"{report.failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
