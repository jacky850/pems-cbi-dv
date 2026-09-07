# Data dictionary

Every column, its unit, and exactly how it is computed. Where a definition
involves a choice, the choice is named.

The key of the main table is **(`corridor`, `link_id`, `period`)**. `link_id`
alone is not unique: 32 link ids occur in two different corridors, because the
D7 and D12 packages number their links independently.

Schema version **0.3**, written into every row and into the summary JSON. This
document maps every column to the canonical cross-repository contract in
[`I405--FDQ-dashboard/docs/VARIABLE_CONTRACT.md`](https://github.com/jacky850/I405--FDQ-dashboard/blob/main/docs/VARIABLE_CONTRACT.md).
Where the two disagree, the contract wins and this file is the defect.

---

## Read this before using `D_counts`, `D_speed` or `DC_hours`

```
D_counts and D_speed are congested-bin passed volumes in vehicles.
They are not the rate-based demand D in D/C.
DC_hours is congested passed volume divided by hourly capacity and has units of
hours. It is not a dimensionless D/C ratio.
```

Those three names were chosen before the cross-repository contract existed and
they say the wrong thing. **They are legacy aliases as of v0.3 and are removed in
v0.4.** Both names carry identical values in this release; `tests/test_units.py`
fails if they ever diverge.

| Legacy name | Canonical name | Unit | Evidence layer |
|---|---|---|---|
| `D_counts` | `congested_passed_volume_counts_veh` | veh | `A_OBSERVED` |
| `D_speed` | `congested_passed_volume_speed_veh` | veh | `B_RECOVERED` |
| `DC_hours` | `capacity_equivalent_hours_counts` | **h** | `A_OBSERVED` |
| `V_counts` | `period_volume_counts_veh` | veh | `A_OBSERVED` |
| `V_speed` | `period_volume_speed_veh` | veh | `B_RECOVERED` |

### Evidence layers

Every quantity here is one of two layers. The distinction is not cosmetic: one is
measured and one is a model output, and they must never be reported as the same
kind of thing.

| Layer | Column | Meaning |
|---|---|---|
| `A_OBSERVED` | `counts_evidence_layer` | detector counts. `flow_vph` and everything summed from it. |
| `B_RECOVERED` | `speed_evidence_layer` | inferred from speed through the S3 fundamental diagram. **Not observed**, however good the fit. |

Layers `C_ASSIGNED_BASELINE` and `D_FINAL_DNL` exist in the contract but nothing
in this repository produces them.

### What is *not* in this repository

The contract's rate-based quantities — `peak_demand_rate_D_vph`,
`demand_modifier_kd`, `dc_rate`, `effective_discharge_mu_vph`,
`capacity_retention_kmu` — are computed in `I405--FDQ-dashboard`, not here. The
one overlap is `mu_vph` / `mu_over_C`, which are this repository's measured
discharge rate and retention and do match the contract's definitions.

---

## Conventions that apply throughout

**Average weekday.** Every quantity is read off one 24-hour profile per link,
not off individual days. The profile is the mean over all score-eligible
weekday observations in the selected months, taken separately in each
5-minute-of-day bin. With the default `--months 2025-10` that is 23 weekdays.
Weekends are excluded.

**Score-eligible.** Only raw rows with `is_score_eligible == 1` enter the
average. In this package that flag is exactly `pct_observed >= 75`: at least
three quarters of the underlying lane samples in the 5-minute bin are real
rather than filled. Roughly 44 % of rows qualify. The columns `is_observed` and
`is_missing` are constant across the entire package (1 and 0 on every row) and
therefore select nothing.

**Full cross-section.** `flow_vph`, and so `D`, `V`, `C` and `mu`, are totals
across all lanes, not per-lane values. `capacity_vphpl` is the only per-lane
column.

**Periods.** Four, covering the full day, in local time:

| period | window | hours |
|---|---|---|
| AM | 06:00–09:00 | 3 |
| MD | 09:00–15:00 | 6 |
| PM | 15:00–19:00 | 4 |
| NT | 19:00–06:00 (wraps midnight) | 11 |

---

## Per-link constants

These four are computed once per link and repeated on each of its period rows.

| column | unit | definition |
|---|---|---|
| `free_speed_mph` | mph | 95th percentile of the link's **averaged weekday speed profile**. Selectable with `--vf-source`; `daily` instead takes the 95th percentile of the raw 5-minute weekday readings (median 71.1 vs 69.6 mph). |
| `capacity_vph` | veh/h | 99.5th percentile of the link's **averaged weekday flow profile** — average first, then take the percentile. Selectable with `--capacity-source`. |
| `capacity_vphpl` | veh/h/lane | `capacity_vph / lanes`. |
| `cutoff_mph` | mph | `0.70 × free_speed_mph`. The threshold that defines congestion. |
| `speed_at_capacity_mph` | mph | `free_speed_mph × 2^(-2/m)` with `m = 4`, i.e. `free_speed_mph / √2`. Written `v_c`. |

### The three capacity definitions

`capacity_vph` takes whichever of these `--capacity-source` names, and the
other two are still written to the table so the choice is visible and any row
can be rescaled by hand.

| source | column | median veh/h/lane | how |
|---|---|---|---|
| `profile` *(default)* | `capacity_alt_profile_p995_vph` | 1329 | 99.5th percentile of the averaged weekday flow profile |
| `daily` | `capacity_alt_daily_p995_vph` | 1567 | 99.5th percentile of the raw 5-minute weekday flows |
| `network` | `capacity_alt_network_vph` | 2000 | the package's declared link capacity, a flat 2000 veh/h/lane on all 347 links |

The `profile` and `daily` figures differ because averaging happens before the
percentile in one and after it in the other: each weekday reaches its own
maximum at a slightly different minute, so averaging first spreads one day's
peak across its neighbours' lower values.

Whichever source is selected is used consistently in three places: `k_c` in the
S3 inversion, the denominator of `DC_hours`, and the denominator of
`mu_over_C`. `capacity_source` records which one produced the run.

---

## Identity and geometry

| column | unit | definition |
|---|---|---|
| `corridor` | – | corridor-direction directory name, e.g. `D12_I5_N`. `D7` = Caltrans District 7 (Los Angeles), `D12` = District 12 (Orange County). |
| `link_id` | – | link id within that corridor. Not unique across corridors. |
| `period` | – | AM / MD / PM / NT as tabulated above. |
| `lanes` | count | from `network/lwr_mainline_topology.csv`. |
| `length_mi` | miles | `length_km × 0.621371` from the same file. |
| `bins` | count | 5-minute bins of the profile falling in this period. |
| `bins_below_cutoff` | count | of those, how many are inside a sustained below-cutoff run. |
| `weekdays_averaged` | count | distinct weekday dates contributing to this link's profile. |

---

## Episode geometry

An **episode** is a run of consecutive profile bins with
`speed < cutoff_mph`, lasting at least 30 minutes. Runs shorter than that are
not episodes.

**The profile is a 24-hour cycle, not a line.** A link still below cutoff at
23:55 and again at 00:00 is in one episode, and the two halves are stitched
**before** the 30-minute minimum is applied. Order matters: splitting first can
leave two halves each under 30 minutes, so a genuine multi-hour night episode
disappears entirely rather than being reported as two short ones. `v0.2` split
them; `v0.3` does not.

On the current dataset **no episode wraps midnight**, so this changes no
published number. It is a latent defect fixed and tested rather than a
correction to the results.

An episode is assigned to the period containing its **T2**. Where a link has
more than one episode in a period, the table carries the longest, ties broken
by the deeper trough. Every episode, including the ones not carried, is in
`pems_episodes.csv`.

| column | unit | definition |
|---|---|---|
| `t0_hhmm` | clock | start of the first congested bin of the episode. |
| `T2_hhmm` | clock | the minute of lowest speed within the episode. |
| `t3_hhmm` | clock | end of the last congested bin, i.e. its start plus 5 minutes. |
| `P_h` | hours | `T3 − T0`, equivalently (number of bins) × 5 minutes. |
| `v_t2_mph` | mph | the speed at T2. |
| `severity` | – | `1 − v_t2_mph / speed_at_capacity_mph`. 0 when the trough only touches `v_c`; approaches 1 as the link stops. |
| `mu_vph` | veh/h | median measured flow over the bins from T2 to T3 inclusive. Blank when that span is a single bin. |
| `mu_over_C` | – | `mu_vph / capacity_vph`, with `capacity_vph` as defined above. |
| `window_type` | – | `normal` (P ≤ 6 h), `long` (6 < P ≤ 8 h), `allday_below_cutoff` (P > 8 h). |

Blank episode columns mean this period holds no episode of its own; see
`congestion_source`.

| `congestion_source` | meaning |
|---|---|
| `own_episode` | the period holds an episode; the geometry columns describe it. |
| `spillover_from_XX` | the period has below-cutoff bins, and so a non-zero `D`, but the episode covering them has its T2 in period XX. The geometry columns are blank by design, not missing. |
| `none` | no below-cutoff bins in this period. |

---

## D and V

Both are vehicle counts obtained by summing a flow series over a set of bins
and multiplying by the bin length (5/60 h). They differ only in which bins:

- **V** sums **every** bin in the period.
- **D** sums only the bins inside a sustained below-cutoff run.

Each is computed twice from the same bins, once from each flow series:

- `_counts` uses the measured flow from the profile.
- `_speed` uses flow inferred from speed alone through the S3 fundamental diagram.

| canonical column | legacy alias | unit | definition |
|---|---|---|---|
| `period_volume_counts_veh` | `V_counts` | veh | `Σ(all bins in period) flow_vph × 5/60` |
| `period_volume_speed_veh` | `V_speed` | veh | `Σ(all bins in period) q̂ × 5/60` |
| `congested_passed_volume_counts_veh` | `D_counts` | veh | `Σ(below-cutoff bins in period) flow_vph × 5/60` |
| `congested_passed_volume_speed_veh` | `D_speed` | veh | `Σ(below-cutoff bins in period) q̂ × 5/60` |
| `capacity_equivalent_hours_counts` | `DC_hours` | **hours** | `congested_passed_volume_counts_veh / capacity_vph`. Vehicles divided by an hourly rate, so the result is a duration: 4.9 means about 4.9 hours of work at capacity. **Not** the dimensionless HCM v/c, and not the contract's `dc_rate`. |
| `V_err` | – | % | `(period_volume_speed_veh − period_volume_counts_veh) / period_volume_counts_veh × 100` |
| `D_err` | – | % | same for the congested volume. Blank when the period has no below-cutoff bins — an abstention, not a missing value. |
| `counts_evidence_layer` | – | – | `A_OBSERVED` on every row. |
| `speed_evidence_layer` | – | – | `B_RECOVERED` on every row. |
| `schema_version` | – | – | `0.3`. |

### The S3 inversion, `q̂`

```
v_c = v_f × 2^(-2/m)                        m = 4
k_c = C / v_c
k   = k_c × ((v_f / v)^(m/2) − 1)^(1/m)     density from speed
q̂   = min(k × v, C)                         flow, capped at C
```

`q̂(v)` is single-valued but not monotone: it rises from zero at `v = v_f`,
peaks at `v = v_c` where `q̂ = C`, and falls back towards zero as `v → 0`.

---

## `pems_episodes.csv`

One row per episode, before the one-per-period selection. Keyed by
(`corridor`, `link_id`, `t0_min`). Carries `t0_min`, `T2_min`, `t3_min` in
minutes past midnight, plus `P_h`, `v_t2_mph`, `mu_vph`, `mu_over_C`, `period`,
`bins`, `window_type`, and:

| column | definition |
|---|---|
| `i0`, `i1` | half-open bin index range of the run. For an episode crossing midnight `i1` exceeds 288; index it modulo 288, which is what `run_indices` does. |
| `wraps_midnight` | true when the episode crosses 00:00. `t0_min` is then later in the clock than `t3_min`, which is what a night episode looks like. |
| `touches_edge` | legacy alias, removed in v0.4. In v0.2 it flagged a record that might be half a split episode; now a wrapping run is one record, so it simply marks episodes reaching either end of the day. |

`t0_min`, `T2_min` and `t3_min` are always clock times in `[0, 1440)`. For a
wrapping episode read them as "starts at `t0_min`, troughs at `T2_min`, ends at
`t3_min` the next morning"; `P_h` carries the true duration.

## `data/pems_link_meta.csv`

Written by stage 1, read by stage 2. One row per (`corridor`, `link_id`):
`lanes`, `length_mi`, `order_index` and `detector_id` from
`lwr_mainline_topology.csv`; `network_capacity_vph`; `daily_p995_flow_vph` and
`daily_p95_speed_mph` (the raw-reading percentiles); `weekdays_averaged` and
`raw_observations`.

## `data/pems_average_weekday_5min.csv.gz`

One row per (`corridor`, `link_id`, `minute`): `speed_mph`, `flow_vph`, and `n`
= the number of score-eligible weekday observations averaged into that bin.
