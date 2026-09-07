"""A congestion episode that spans midnight is one episode, not two, and not none.

The profile is a 24-hour cycle but the runs were found on a linear 00:00-23:55
array, so a link still below cutoff at 23:55 and again at 00:00 produced two
records. Worse, the 30-minute minimum was applied to each half, so a genuine
night episode with short halves vanished entirely.

`sustained_runs` now stitches the two halves **before** the minimum-duration
rule. The stitched run is returned with `end > len(profile)` and indexed modulo
the length by `run_indices`.
"""

from __future__ import annotations

import numpy as np
import pytest

from pems_cbi.analysis import (episodes_for_link, run_indices, sustained_runs,
                               period_of)
from pems_cbi.config import DT_MIN, MIN_EPISODE_H, SLOTS_PER_DAY, STEP_H

MIN_BINS = int(round(MIN_EPISODE_H / STEP_H))       # 6 bins = 30 minutes


def profile(below_indices, n=SLOTS_PER_DAY):
    below = np.zeros(n, dtype=bool)
    below[list(below_indices)] = True
    return below


def test_run_wholly_inside_the_day_is_unchanged():
    below = profile(range(100, 120))
    assert sustained_runs(below, MIN_BINS) == [(100, 120)]


def test_short_dip_is_still_not_an_episode():
    below = profile(range(100, 100 + MIN_BINS - 1))
    assert sustained_runs(below, MIN_BINS) == []


def test_halves_at_both_ends_become_one_run():
    """20 bins before midnight and 10 after are one 30-bin episode."""
    n = SLOTS_PER_DAY
    below = profile(list(range(0, 10)) + list(range(n - 20, n)))
    runs = sustained_runs(below, MIN_BINS)
    assert runs == [(n - 20, n + 10)], runs
    a, b = runs[0]
    assert b - a == 30
    assert list(run_indices(a, b, n)) == list(range(n - 20, n)) + list(range(0, 10))


def test_stitching_happens_before_the_minimum_duration_rule():
    """This is the case the old code lost entirely.

    Four bins each side: neither half reaches the 6-bin minimum, so splitting
    first drops both. Stitched, it is an 8-bin episode that should be kept.
    """
    n = SLOTS_PER_DAY
    below = profile(list(range(0, 4)) + list(range(n - 4, n)))

    assert sustained_runs(below, MIN_BINS, wrap=False) == [], (
        "the linear reading finds two 4-bin runs and drops both")
    assert sustained_runs(below, MIN_BINS) == [(n - 4, n + 4)], (
        "the cyclic reading finds one 8-bin episode")


def test_a_day_entirely_below_cutoff_stays_one_run():
    """The guard against stitching a single full-day run onto itself."""
    n = SLOTS_PER_DAY
    runs = sustained_runs(np.ones(n, dtype=bool), MIN_BINS)
    assert runs == [(0, n)]
    assert runs[0][1] - runs[0][0] == n


def test_edge_run_at_one_end_only_is_not_stitched():
    """Below cutoff at 00:00 but recovered well before 23:55: nothing to join."""
    below = profile(range(0, 20))
    assert sustained_runs(below, MIN_BINS) == [(0, 20)]


def test_wrapping_episode_reports_one_record_with_the_full_duration():
    n = SLOTS_PER_DAY
    minute = np.arange(n, dtype=float) * DT_MIN
    speed = np.full(n, 65.0)
    flow = np.full(n, 1200.0)
    # 21:00-01:00, four hours across midnight, trough at 23:30.
    night = list(range(n - 36, n)) + list(range(0, 12))
    speed[night] = 30.0
    speed[282] = 12.0                                  # 23:30
    cutoff = 0.70 * 65.0

    eps = episodes_for_link(speed, flow, minute, cutoff, capacity=2000.0,
                            min_bins=MIN_BINS)
    assert len(eps) == 1, f"expected one stitched episode, got {len(eps)}"
    e = eps[0]
    assert e["wraps_midnight"] is True
    assert e["bins"] == 48
    assert e["P_h"] == pytest.approx(4.0)
    assert e["t0_min"] == pytest.approx((n - 36) * DT_MIN)      # 21:00
    assert e["T2_min"] == pytest.approx(282 * DT_MIN)           # 23:30
    assert e["v_t2_mph"] == pytest.approx(12.0)
    # t3 is a clock time, so it wraps: 01:00, not 25:00.
    assert e["t3_min"] == pytest.approx(60.0)
    assert e["period"] == "NT" == period_of(e["T2_min"])


def test_the_split_version_would_have_reported_two_shorter_episodes():
    """States plainly what the old behaviour was, so the change is legible."""
    n = SLOTS_PER_DAY
    minute = np.arange(n, dtype=float) * DT_MIN
    speed = np.full(n, 65.0)
    flow = np.full(n, 1200.0)
    speed[list(range(n - 36, n)) + list(range(0, 12))] = 30.0
    cutoff = 0.70 * 65.0

    linear = sustained_runs(speed < cutoff, MIN_BINS, wrap=False)
    assert len(linear) == 2
    assert sorted(b - a for a, b in linear) == [12, 36]

    cyclic = sustained_runs(speed < cutoff, MIN_BINS)
    assert len(cyclic) == 1
    assert cyclic[0][1] - cyclic[0][0] == 48


def test_published_episodes_carry_the_wrapping_flag():
    """The real dataset has none; the column must still be there and be boolean."""
    from pathlib import Path

    import pandas as pd

    path = Path(__file__).resolve().parents[1] / "outputs/pems_episodes.csv"
    if not path.exists():
        pytest.skip("run `python -m pems_cbi.run table` first")
    episodes = pd.read_csv(path)
    assert "wraps_midnight" in episodes
    assert episodes["wraps_midnight"].dtype == bool
    wrapping = episodes[episodes["wraps_midnight"]]
    # Every wrapping episode must have t0 later in the clock than t3.
    assert (wrapping["t0_min"] > wrapping["t3_min"]).all()
