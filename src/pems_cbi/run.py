"""Command-line entry point.

    python -m pems_cbi.run profiles --package <TrafficFlowBench corridors dir>
    python -m pems_cbi.run table

`profiles` reads the raw parquet package and writes the two files in data/.
`table` reads only those two files, so it runs on a fresh clone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import analysis, profiles

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pems_cbi.run", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="stage", required=True)

    p1 = sub.add_parser("profiles", help="raw parquet -> average-weekday profile + link meta")
    p1.add_argument("--package", type=Path, required=True,
                    help="the kaggle_release/corridors directory of the five-corridor package")
    p1.add_argument("--corridors", nargs="*", default=None,
                    help="default: every corridor directory in the package")
    p1.add_argument("--months", nargs="*", default=["2025-10"],
                    help="year_month partitions to average, or 'all'. Default 2025-10.")
    p1.add_argument("--min-observations", type=int, default=10,
                    help="score-eligible weekday observations a link-bin needs to be kept")
    p1.add_argument("--data-dir", type=Path, default=DATA)

    p2 = sub.add_parser("table", help="average-weekday profile -> link x period table")
    p2.add_argument("--data-dir", type=Path, default=DATA)
    p2.add_argument("--output-dir", type=Path, default=OUTPUTS)
    p2.add_argument("--capacity-source", default="profile",
                    choices=["profile", "daily", "network"],
                    help="how capacity_vph is defined; see DATA_DICTIONARY.md")
    p2.add_argument("--vf-source", default="profile", choices=["profile", "daily"],
                    help="how free_speed_mph is defined; see DATA_DICTIONARY.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.stage == "profiles":
        months = None if args.months == ["all"] else list(args.months)
        profile_path, meta_path = profiles.build(
            args.package, args.corridors, months, args.min_observations, args.data_dir)
        print(f"\nWrote {profile_path}\n      {meta_path}")
        return

    profile = pd.read_csv(args.data_dir / "pems_average_weekday_5min.csv.gz")
    meta = pd.read_csv(args.data_dir / "pems_link_meta.csv")
    table, episodes = analysis.build_table(
        profile, meta, capacity_source=args.capacity_source, vf_source=args.vf_source)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output_dir / "pems_cbi_link_period.csv", index=False)
    episodes.to_csv(args.output_dir / "pems_episodes.csv", index=False)
    summary = analysis.summarise(table)
    (args.output_dir / "pems_cbi_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(f"{summary['links']} links, {summary['rows']} link-periods, "
          f"{summary['episodes']} episodes")
    print(f"\n{'period':<8}{'D n':>6}{'D MAPE':>9}{'V n':>6}{'V MAPE':>9}")
    for p, s in summary["by_period"].items():
        d, v = s["D"], s["V"]
        print(f"{p:<8}{d['n']:>6}{d.get('mape_pct', float('nan')):>8}%"
              f"{v['n']:>6}{v.get('mape_pct', float('nan')):>8}%")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
