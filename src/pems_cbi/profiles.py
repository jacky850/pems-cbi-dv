"""Stage 1 -- raw PeMS parquet to an average-weekday profile.

Input   the TrafficFlowBench five-corridor package (daily 5-minute parquet)
Output  data/pems_average_weekday_5min.csv.gz   one row per link x 5-minute bin
        data/pems_link_meta.csv                 one row per link

Stage 2 reads only those two files, so the large raw package is needed once.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import (CAPACITY_Q, FREE_SPEED_Q, KM_TO_MI, RAW_COLUMNS)


def _weekday_files(corridor_dir: Path, months: list[str] | None) -> list[Path]:
    states = corridor_dir / "train" / "mainline_states"
    if months is None:
        return sorted(states.rglob("*.parquet"))
    return sorted(f for m in months for f in (states / f"year_month={m}").glob("*.parquet"))


def build_corridor(corridor_dir: Path, months: list[str] | None,
                   min_observations: int) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Average-weekday profile and per-link metadata for one corridor.

    Only rows with ``is_score_eligible == 1`` are used. That flag is exactly
    ``pct_observed >= 75``: at least three quarters of the underlying lane
    samples in the 5-minute bin are real. ``is_observed`` and ``is_missing``
    are constant across the whole package (1 and 0 on every row) and so cannot
    be used to select anything.

    Weekends are excluded. Within each 5-minute-of-day bin the surviving
    weekday observations are averaged, which is the "average weekday" profile.
    """
    totals, weekdays = None, set()
    raw_flow: dict[str, list] = {}
    raw_speed: dict[str, list] = {}

    for path in _weekday_files(corridor_dir, months):
        chunk = pd.read_parquet(path, columns=RAW_COLUMNS)
        chunk = chunk[chunk["is_score_eligible"] == 1]
        chunk = chunk.dropna(subset=["speed_kmh", "flow_vph"])
        if chunk.empty:
            continue
        # The stamps carry a "Z" but are already local time: each file runs
        # 00:00-23:55 of its own date. Parsing them as UTC shifts the profile
        # seven hours and moves the PM peak into the morning.
        stamp = pd.to_datetime(chunk["timestamp"].str.slice(0, 19), format="ISO8601")
        chunk = chunk.assign(minute=stamp.dt.hour * 60 + stamp.dt.minute,
                             weekday=pd.to_datetime(chunk["date"]).dt.weekday)
        chunk = chunk[chunk["weekday"] < 5]
        if chunk.empty:
            continue
        weekdays.update(chunk["date"].unique())
        for link_id, g in chunk.groupby("link_id", sort=False):
            raw_flow.setdefault(link_id, []).append(g["flow_vph"].to_numpy(float))
            raw_speed.setdefault(link_id, []).append(g["speed_kmh"].to_numpy(float))
        part = (chunk.groupby(["link_id", "minute"])
                .agg(speed_sum=("speed_kmh", "sum"), flow_sum=("flow_vph", "sum"),
                     n=("flow_vph", "size")))
        totals = part if totals is None else totals.add(part, fill_value=0)

    if totals is None:
        return pd.DataFrame(), pd.DataFrame(), 0

    profile = totals.reset_index()
    profile = profile[profile["n"] >= min_observations]
    profile["speed_mph"] = profile["speed_sum"] / profile["n"] * KM_TO_MI
    profile["flow_vph"] = profile["flow_sum"] / profile["n"]
    profile = profile[["link_id", "minute", "speed_mph", "flow_vph", "n"]]

    # Geometry and the network's own declared capacity. lwr_mainline_topology
    # is present for all ten corridors; fd_parameters.csv is not (only the four
    # D12 ones ship it), so it is deliberately not read here.
    topo = pd.read_csv(corridor_dir / "network" / "lwr_mainline_topology.csv")
    topo = topo.drop_duplicates("link_id").set_index("link_id")

    meta = []
    for link_id, parts in raw_flow.items():
        flow = np.concatenate(parts)
        speed = np.concatenate(raw_speed[link_id]) * KM_TO_MI
        if flow.size < min_observations or flow.max() <= 0:
            continue
        row = dict(link_id=link_id, weekdays_averaged=len(weekdays),
                   raw_observations=int(flow.size),
                   # the same two percentiles taken over the raw 5-minute
                   # readings rather than over the averaged profile
                   daily_p995_flow_vph=float(np.quantile(flow, CAPACITY_Q)),
                   daily_p95_speed_mph=float(np.quantile(speed, FREE_SPEED_Q)))
        if link_id in topo.index:
            t = topo.loc[link_id]
            row.update(lanes=int(t["lanes"]),
                       length_mi=round(float(t["length_km"]) * KM_TO_MI, 4),
                       network_capacity_vph=float(t["capacity_vph"]),
                       order_index=int(t["order_index"]),
                       detector_id=t.get("detector_id", np.nan))
        meta.append(row)

    return profile, pd.DataFrame(meta), len(weekdays)


def build(package: Path, corridors: list[str] | None, months: list[str] | None,
          min_observations: int, out_dir: Path) -> tuple[Path, Path]:
    """Run stage 1 over every corridor and write the two stage-2 inputs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    names = corridors or sorted(d.name for d in package.iterdir()
                                if d.is_dir() and (d / "network").exists())
    profiles, metas = [], []
    for name in names:
        profile, meta, n_weekdays = build_corridor(package / name, months, min_observations)
        if profile.empty:
            print(f"  {name:<12} no score-eligible observations")
            continue
        profile.insert(0, "corridor", name)
        meta.insert(0, "corridor", name)
        profiles.append(profile)
        metas.append(meta)
        print(f"  {name:<12} {profile['link_id'].nunique():>4} links, "
              f"{n_weekdays:>3} weekdays", flush=True)

    profile_path = out_dir / "pems_average_weekday_5min.csv.gz"
    meta_path = out_dir / "pems_link_meta.csv"
    pd.concat(profiles, ignore_index=True).to_csv(profile_path, index=False, compression="gzip")
    pd.concat(metas, ignore_index=True).to_csv(meta_path, index=False)
    return profile_path, meta_path
