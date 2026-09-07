"""Stage 2 -- average-weekday profile to the link x period table.

Input   data/pems_average_weekday_5min.csv.gz + data/pems_link_meta.csv
Output  outputs/pems_cbi_link_period.csv    one row per link x period
        outputs/pems_episodes.csv           one row per congestion episode

Every quantity is defined in DATA_DICTIONARY.md; the code below is the
authority for how each is actually computed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (ALLDAY_P_H, CAPACITY_Q, CUTOFF_RATIO, DT_MIN, FREE_SPEED_Q,
                     LONG_P_H, LONG_P_H as _LONG, MIN_EPISODE_H, MIN_PROFILE_BINS,
                     PERIODS, S3_M, STEP_H)


# --------------------------------------------------------------------- helpers

def speed_at_capacity(free_speed: float) -> float:
    """v_c = v_f * 2^(-2/m). With m = 4 this is v_f / sqrt(2)."""
    return free_speed * 2.0 ** (-2.0 / S3_M)


def s3_flow(speed: np.ndarray, free_speed: float, capacity: float) -> np.ndarray:
    """Flow implied by speed through the S3 fundamental diagram.

        k = k_c * ((v_f / v)^(m/2) - 1)^(1/m)      density from speed
        q = min(k * v, C)                          flow, capped at C

    with k_c = C / v_c. q(v) is single-valued but not monotone: it rises from
    zero at v_f, peaks at v_c, and falls back towards zero as v -> 0.
    """
    v_c = speed_at_capacity(free_speed)
    k_c = capacity / v_c
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    density = k_c * np.maximum((free_speed / v) ** (S3_M / 2.0) - 1.0, 0.0) ** (1.0 / S3_M)
    return np.minimum(density * v, capacity)


def sustained_runs(below: np.ndarray, min_bins: int, wrap: bool = True) -> list[tuple[int, int]]:
    """Half-open [start, end) ranges of below-cutoff runs of at least min_bins.

    The minimum length is what separates an episode from a one-bin dip.

    With ``wrap`` (the default) the profile is a 24-hour cycle, not a line: a
    link still below cutoff at 23:55 and again at 00:00 is in one episode, and
    the run that spans midnight is returned as a single range whose ``end``
    exceeds the profile length. Callers index it with :func:`run_indices`.

    **The stitch happens before the minimum-duration rule**, which is the part
    that matters. Splitting first can leave two halves each shorter than
    ``min_bins``, so a genuine multi-hour night episode disappears entirely
    rather than being reported as two short ones.

    ``wrap=False`` restores the old linear behaviour, and is what
    :func:`build_table` uses when it needs plain within-day indices.
    """
    raw, start = [], None
    for i, flag in enumerate(np.append(below, False)):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            raw.append((start, i))
            start = None

    n = len(below)
    if wrap and len(raw) >= 2 and raw[0][0] == 0 and raw[-1][1] == n:
        # First and last runs are the two halves of one episode across midnight.
        # A single run covering the whole day is already one range and is left
        # alone by the len >= 2 guard.
        first, last = raw[0], raw[-1]
        raw = raw[1:-1] + [(last[0], first[1] + n)]

    return [(a, b) for a, b in raw if b - a >= min_bins]


def run_indices(a: int, b: int, n: int) -> np.ndarray:
    """Profile bin indices of the run [a, b), wrapping past the end of the day."""
    return np.arange(a, b) % n


def period_of(minute: float) -> str:
    for name, (start, end) in PERIODS.items():
        inside = (start <= minute < end) if end <= 1440 else (minute >= start or minute < end - 1440)
        if inside:
            return name
    return "NT"


def hhmm(minute: float) -> str:
    m = int(round(minute)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def window_type(p_h: float) -> str:
    """normal / long (P > 6 h) / allday_below_cutoff (P > 8 h).

    The same three classes the NVTA study uses, so the two are comparable.
    """
    if p_h > ALLDAY_P_H:
        return "allday_below_cutoff"
    if p_h > LONG_P_H:
        return "long"
    return "normal"


# -------------------------------------------------------------------- episodes

def episodes_for_link(speed: np.ndarray, flow: np.ndarray, minute: np.ndarray,
                      cutoff: float, capacity: float, min_bins: int) -> list[dict]:
    """One record per sustained below-cutoff run on the 24-hour profile.

    T0  start of the first congested bin
    T2  the minute of the lowest speed in the run
    T3  end of the last congested bin, i.e. its start + 5 minutes
    P   T3 - T0, equivalently (number of bins) x 5 minutes
    mu  median measured flow over the bins from T2 to T3

    The profile is treated as a 24-hour cycle, so a run straddling midnight is
    one episode rather than two. wraps_midnight marks those; t0_min then exceeds
    t3_min in clock terms, which is what a night episode looks like.
    """
    n = len(speed)
    out = []
    for a, b in sustained_runs(speed < cutoff, min_bins):
        index = run_indices(a, b, n)
        seg_speed, seg_flow, seg_min = speed[index], flow[index], minute[index]
        j = int(np.argmin(seg_speed))
        t0, t2 = float(seg_min[0]), float(seg_min[j])
        t3 = (float(seg_min[-1]) + DT_MIN) % 1440.0
        drain = seg_flow[j:]
        mu = float(np.median(drain)) if len(drain) >= 2 else np.nan
        p_h = (b - a) * STEP_H
        out.append(dict(
            i0=a, i1=b,
            t0_min=t0, T2_min=t2, t3_min=t3, P_h=p_h,
            v_t2_mph=float(seg_speed[j]), mu_vph=mu,
            mu_over_C=mu / capacity if np.isfinite(mu) and capacity > 0 else np.nan,
            period=period_of(t2), bins=b - a,
            window_type=window_type(p_h),
            wraps_midnight=bool(b > n),
            # Retained for one release under its old name and meaning. Before
            # the stitch this flagged a record that might be half an episode;
            # now a wrapping run is one record, so the two coincide.
            touches_edge=bool(b > n or a == 0 or b == n)))
    return out


# ----------------------------------------------------------------- the table

def build_table(profile: pd.DataFrame, meta: pd.DataFrame,
                capacity_source: str = "profile",
                vf_source: str = "profile") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assemble the link x period table and the episode list."""
    min_bins = int(round(MIN_EPISODE_H / STEP_H))
    meta = meta.set_index(["corridor", "link_id"])
    rows, episode_rows = [], []

    for (corridor, link_id), g in profile.groupby(["corridor", "link_id"], sort=True):
        g = g.sort_values("minute")
        speed = g["speed_mph"].to_numpy(float)
        flow = g["flow_vph"].to_numpy(float)
        minute = g["minute"].to_numpy(float)
        if len(g) < MIN_PROFILE_BINS or flow.max() <= 0:
            continue
        if (corridor, link_id) not in meta.index:
            continue
        m = meta.loc[(corridor, link_id)]

        # One capacity, one definition, used in k_c, D/C and mu/C alike. The
        # two alternatives ride along as columns so the choice stays visible.
        profile_p995 = float(np.quantile(flow, CAPACITY_Q))
        daily_p995 = float(m["daily_p995_flow_vph"])
        network_cap = float(m.get("network_capacity_vph", np.nan))
        capacity = {"profile": profile_p995, "daily": daily_p995,
                    "network": network_cap}[capacity_source]
        free_speed = (float(np.quantile(speed, FREE_SPEED_Q)) if vf_source == "profile"
                      else float(m["daily_p95_speed_mph"]))
        if not free_speed > 0 or not capacity > 0:
            continue

        cutoff = CUTOFF_RATIO * free_speed
        v_c = speed_at_capacity(free_speed)
        q_hat = s3_flow(speed, free_speed, capacity)

        eps = episodes_for_link(speed, flow, minute, cutoff, capacity, min_bins)
        for e in eps:
            episode_rows.append(dict(corridor=corridor, link_id=link_id, **e))

        # One episode per period reaches the table: the longest, ties broken by
        # the deeper trough.
        best: dict[str, dict] = {}
        for e in eps:
            cur = best.get(e["period"])
            if cur is None or (e["P_h"], -e["v_t2_mph"]) > (cur["P_h"], -cur["v_t2_mph"]):
                best[e["period"]] = e

        below = np.zeros(len(speed), dtype=bool)
        for a, b in sustained_runs(speed < cutoff, min_bins):
            below[run_indices(a, b, len(speed))] = True
        period = np.array([period_of(x) for x in minute])
        lanes = int(m["lanes"]) if np.isfinite(m.get("lanes", np.nan)) else np.nan

        for p in PERIODS:
            k = period == p
            if not k.any() or flow[k].sum() <= 0:
                continue
            e = best.get(p, {})
            # An episode belongs to the period holding its T2, but its
            # below-cutoff bins are counted wherever they fall, so a period can
            # carry D without owning an episode. congestion_source says which.
            if e:
                source = "own_episode"
            elif (k & below).any():
                spill = sorted({ep["period"] for ep in eps
                                if k[run_indices(ep["i0"], ep["i1"], len(speed))].any()})
                source = "spillover_from_" + "+".join(spill) if spill else "unassigned"
            else:
                source = "none"

            # Vehicles that passed during the congested bins, counted and
            # speed-inferred, and the period totals over every bin.
            congested_counts = float(flow[k & below].sum() * STEP_H)
            congested_speed = float(q_hat[k & below].sum() * STEP_H)
            volume_counts = float(flow[k].sum() * STEP_H)
            volume_speed = float(q_hat[k].sum() * STEP_H)
            rows.append({
                "corridor": corridor, "link_id": link_id, "period": p,
                "lanes": lanes, "length_mi": m.get("length_mi", np.nan),
                "bins": int(k.sum()), "bins_below_cutoff": int((k & below).sum()),
                "weekdays_averaged": int(m["weekdays_averaged"]),
                "free_speed_mph": free_speed,
                "speed_at_capacity_mph": v_c,
                "cutoff_mph": cutoff,
                "capacity_vph": capacity,
                "capacity_vphpl": capacity / lanes if lanes == lanes else np.nan,
                "capacity_source": capacity_source,
                "capacity_alt_profile_p995_vph": profile_p995,
                "capacity_alt_daily_p995_vph": daily_p995,
                "capacity_alt_network_vph": network_cap,
                "t0_hhmm": hhmm(e["t0_min"]) if e else "",
                "T2_hhmm": hhmm(e["T2_min"]) if e else "",
                "t3_hhmm": hhmm(e["t3_min"]) if e else "",
                "P_h": e.get("P_h", np.nan),
                "window_type": e.get("window_type", ""),
                "congestion_source": source,
                "v_t2_mph": e.get("v_t2_mph", np.nan),
                "severity": (1.0 - e["v_t2_mph"] / v_c) if e else np.nan,
                "mu_vph": e.get("mu_vph", np.nan),
                "mu_over_C": e.get("mu_over_C", np.nan),

                # --- canonical names, v0.3 -------------------------------
                # These four are VEHICLE COUNTS, not the rate-based demand D
                # that appears in D/C. See the variable contract.
                "congested_passed_volume_counts_veh": congested_counts,
                "congested_passed_volume_speed_veh": congested_speed,
                "period_volume_counts_veh": volume_counts,
                "period_volume_speed_veh": volume_speed,
                # Vehicles divided by an hourly rate, so this is a DURATION in
                # hours: how long the congested traffic would take to clear at
                # capacity. It is not the dimensionless HCM v/c, and must never
                # be labelled D/C.
                "capacity_equivalent_hours_counts": congested_counts / capacity,
                "counts_evidence_layer": "A_OBSERVED",
                "speed_evidence_layer": "B_RECOVERED",
                "schema_version": "0.3",

                # --- legacy aliases, one release only --------------------
                # Identical values under the old names, so an existing reader
                # keeps working while the names move. Asserted equal in
                # tests/test_units.py. Removed in v0.4.
                "DC_hours": congested_counts / capacity,
                "D_counts": congested_counts,
                "D_speed": congested_speed,
                "V_counts": volume_counts,
                "V_speed": volume_speed,
            })

    table = pd.DataFrame(rows)
    table["V_err"] = ((table["period_volume_speed_veh"] - table["period_volume_counts_veh"])
                      / table["period_volume_counts_veh"] * 100)
    congested = table["bins_below_cutoff"] > 0
    table.loc[congested, "D_err"] = (
        (table.loc[congested, "congested_passed_volume_speed_veh"]
         - table.loc[congested, "congested_passed_volume_counts_veh"])
        / table.loc[congested, "congested_passed_volume_counts_veh"] * 100)
    return table, pd.DataFrame(episode_rows)


def summarise(table: pd.DataFrame, episodes: pd.DataFrame | None = None) -> dict:
    """Accuracy, plus the exact inventory of what was kept and what was dropped.

    A MAPE with no denominator behind it is not reportable, so the counts sit
    beside the errors rather than in a separate note.
    """
    def score(s: pd.Series) -> dict:
        s = s.dropna()
        if not len(s):
            return {"n": 0}
        return {"n": int(len(s)), "mape_pct": round(float(s.abs().mean()), 1),
                "median_bias_pct": round(float(s.median()), 1)}

    summary: dict = {
        "schema_version": "0.3",
        "rows": int(len(table)),
        "links": int(table.groupby(["corridor", "link_id"]).ngroups),
        "episodes": int(table["P_h"].notna().sum()),
        "capacity_source": str(table["capacity_source"].iloc[0]),
        "inventory": {
            "corridors": int(table["corridor"].nunique()),
            "links": int(table.groupby(["corridor", "link_id"]).ngroups),
            "link_periods": int(len(table)),
            "link_periods_with_an_episode": int((table["congestion_source"] == "own_episode").sum()),
            "link_periods_with_spillover_only": int(
                table["congestion_source"].str.startswith("spillover_from_").sum()),
            "link_periods_uncongested": int((table["congestion_source"] == "none").sum()),
            "rows_scored_for_D": int(table["D_err"].notna().sum()),
            "rows_excluded_from_D": int(table["D_err"].isna().sum()),
            "rows_scored_for_V": int(table["V_err"].notna().sum()),
            "note": ("D is scored only where the period has below-cutoff bins. "
                     "Excluded rows are uncongested, not missing."),
        },
        "by_period": {p: {"D": score(table.loc[table["period"] == p, "D_err"]),
                          "V": score(table.loc[table["period"] == p, "V_err"])}
                      for p in PERIODS},
        "by_corridor": {c: score(g["D_err"]) for c, g in table.groupby("corridor")},
    }

    if episodes is not None and len(episodes):
        wrapping = int(episodes.get("wraps_midnight", pd.Series(dtype=bool)).sum())
        summary["episodes_detail"] = {
            "total": int(len(episodes)),
            "carried_into_the_table": int((table["congestion_source"] == "own_episode").sum()),
            "not_carried": int(len(episodes) - (table["congestion_source"] == "own_episode").sum()),
            "wrapping_midnight": wrapping,
            "by_window_type": {k: int(v) for k, v in
                               episodes["window_type"].value_counts().items()},
            "by_period": {k: int(v) for k, v in episodes["period"].value_counts().items()},
            "note": ("A run below cutoff at both 23:55 and 00:00 is stitched into one "
                     "episode before the 30-minute minimum is applied, so it is not "
                     "reported as two short ones or dropped."),
        }
    return summary
