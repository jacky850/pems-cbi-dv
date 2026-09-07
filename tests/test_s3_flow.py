"""The S3 inversion has properties that follow from the algebra, not from data.

    v_c = v_f * 2^(-2/m)                      m = 4, so v_c = v_f / sqrt(2)
    k_c = C / v_c
    k   = k_c * ((v_f/v)^(m/2) - 1)^(1/m)
    q   = min(k * v, C)

The one that matters downstream: q peaks at exactly C when v = v_c. The
congestion cut-off sits at 0.70 v_f while the capacity speed is 0.7071 v_f, so
any "maximum flow before breakdown" window sweeps that point and returns C
whatever C was assumed. That is why capacity is an input here, not an estimate.
"""

from __future__ import annotations

import numpy as np
import pytest

from pems_cbi.analysis import s3_flow, speed_at_capacity
from pems_cbi.config import CUTOFF_RATIO, S3_M

FREE_SPEED = 65.0
CAPACITY = 2000.0


def test_capacity_speed_is_free_speed_over_root_two():
    assert speed_at_capacity(FREE_SPEED) == pytest.approx(FREE_SPEED / np.sqrt(2.0))
    assert S3_M == 4.0, "the identity above holds for m = 4"


def test_flow_equals_capacity_at_the_capacity_speed():
    v_c = speed_at_capacity(FREE_SPEED)
    assert s3_flow(np.array([v_c]), FREE_SPEED, CAPACITY)[0] == pytest.approx(CAPACITY)


def test_flow_peaks_at_the_capacity_speed():
    speed = np.linspace(0.5, FREE_SPEED - 1e-6, 4000)
    flow = s3_flow(speed, FREE_SPEED, CAPACITY)
    assert speed[int(np.argmax(flow))] == pytest.approx(speed_at_capacity(FREE_SPEED), rel=1e-3)


def test_flow_is_never_above_capacity():
    speed = np.linspace(0.01, FREE_SPEED - 1e-6, 5000)
    assert s3_flow(speed, FREE_SPEED, CAPACITY).max() <= CAPACITY + 1e-9


def test_flow_is_not_monotone_in_speed():
    """Both a fast empty road and a slow jammed one carry little flow.

    This is why speed alone does not identify volume, and the reason the whole
    project needs a queue before speed says anything about how many vehicles
    passed.
    """
    free_flowing = s3_flow(np.array([FREE_SPEED * 0.98]), FREE_SPEED, CAPACITY)[0]
    at_capacity = s3_flow(np.array([speed_at_capacity(FREE_SPEED)]), FREE_SPEED, CAPACITY)[0]
    jammed = s3_flow(np.array([FREE_SPEED * 0.05]), FREE_SPEED, CAPACITY)[0]
    assert free_flowing < at_capacity
    assert jammed < at_capacity


def test_the_cutoff_sits_just_below_the_capacity_speed():
    """0.70 v_f against 0.7071 v_f: 1% apart, which is the identifiability trap."""
    v_c = speed_at_capacity(FREE_SPEED)
    cutoff = CUTOFF_RATIO * FREE_SPEED
    assert cutoff < v_c
    assert (v_c - cutoff) / v_c < 0.02
    # Flow at the cut-off is therefore within a fraction of a per cent of C,
    # whatever C is assumed to be.
    at_cutoff = s3_flow(np.array([cutoff]), FREE_SPEED, CAPACITY)[0]
    assert at_cutoff / CAPACITY > 0.99


@pytest.mark.parametrize("capacity", [1800.0, 2000.0, 2200.0, 2400.0])
def test_flow_at_the_cutoff_scales_exactly_with_assumed_capacity(capacity):
    """q/C at the cut-off does not depend on C, so C cannot be recovered from it."""
    cutoff = CUTOFF_RATIO * FREE_SPEED
    ratio = s3_flow(np.array([cutoff]), FREE_SPEED, capacity)[0] / capacity
    reference = s3_flow(np.array([cutoff]), FREE_SPEED, 2000.0)[0] / 2000.0
    assert ratio == pytest.approx(reference, abs=1e-12)


def test_speeds_at_or_above_free_speed_are_clipped_not_nan():
    flow = s3_flow(np.array([FREE_SPEED, FREE_SPEED * 1.2]), FREE_SPEED, CAPACITY)
    assert np.isfinite(flow).all()
    assert (flow >= 0).all()
