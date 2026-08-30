"""Every constant the pipeline uses, in one place.

Nothing here is fitted at run time; these are the choices that define the
quantities. Changing one changes what D, V, P and T2 mean, so they live
together rather than being scattered through the code.
"""

from __future__ import annotations

KM_TO_MI = 0.621371192237334

DT_MIN = 5                      # native PeMS cadence, minutes
STEP_H = DT_MIN / 60.0
SLOTS_PER_DAY = 1440 // DT_MIN  # 288

# The four assignment periods, in minutes past local midnight. NT wraps: it
# runs 19:00 to 06:00 the next day, written as 1140..1800.
PERIODS: dict[str, tuple[int, int]] = {
    "AM": (360, 540),     # 06:00-09:00,  3 h
    "MD": (540, 900),     # 09:00-15:00,  6 h
    "PM": (900, 1140),    # 15:00-19:00,  4 h
    "NT": (1140, 1800),   # 19:00-06:00, 11 h
}

CUTOFF_RATIO = 0.70     # congested when speed < CUTOFF_RATIO * v_f
S3_M = 4.0              # S3 exponent; speed at capacity = v_f * 2^(-2/m) = v_f/sqrt(2)
MIN_EPISODE_H = 0.5     # a below-cutoff run shorter than this is not an episode
FREE_SPEED_Q = 0.95     # v_f  = this percentile of the speed profile
CAPACITY_Q = 0.995      # C    = this percentile of the flow profile
MIN_PROFILE_BINS = 200  # of 288; a link with fewer is dropped

# window_type thresholds, in hours of P
LONG_P_H = 6.0
ALLDAY_P_H = 8.0

# Columns read from the raw parquet. is_score_eligible is the flag that
# separates measurement from fill; see README.
RAW_COLUMNS = ["date", "timestamp", "link_id", "speed_kmh", "flow_vph",
               "pct_observed", "is_score_eligible", "is_imputed"]
