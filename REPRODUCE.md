# Reproducing these results

Everything in `outputs/` regenerates from `data/`, which is in the repository.
No external package, no personal path, no `PYTHONPATH`.

```bash
git clone https://github.com/jacky850/pems-cbi-dv.git
cd pems-cbi-dv
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e ".[test]"
pytest -q
python -m pems_cbi.run table
python -m pems_cbi.run figure
python scripts/validate_outputs.py
```

Expected:

```
37 passed
10 corridors, 347 links, 1388 link-periods, 282 episodes
all checks passed
```

`python -m pems_cbi.run table` prints its own inventory before the accuracy
table, because a MAPE without its denominators is not reportable:

```
10 corridors, 347 links, 1388 link-periods, 282 episodes
  link-periods: 269 with an episode, 242 spillover only, 877 uncongested
  scored: D on 511 rows (877 excluded as uncongested), V on 1388
  episodes: 269 carried, 13 not carried, 0 wrapping midnight
```

---

## What each stage reads and writes

| Stage | Reads | Writes |
|---|---|---|
| `profiles` | the external five-corridor parquet package | `data/pems_average_weekday_5min.csv.gz`, `data/pems_link_meta.csv` |
| `table` | those two files | `outputs/pems_cbi_link_period.csv`, `outputs/pems_episodes.csv`, `outputs/pems_cbi_summary.json` |
| `figure` | the link-period table | `outputs/d_v_vs_counts.png` |

**`table` and `figure` run on a fresh clone.** `profiles` needs the raw package
and is only rerun when the source months or the eligibility rule change:

```bash
python -m pems_cbi.run profiles --package /path/to/kaggle_release/corridors
```

---

## Changing a definition

Three flags change what the quantities mean. Each is recorded in the output so a
row can be traced back to the run that produced it.

```bash
python -m pems_cbi.run table --capacity-source daily     # profile | daily | network
python -m pems_cbi.run table --vf-source daily           # profile | daily
```

`capacity_source` is written into every row. The two capacities not selected ride
along as `capacity_alt_*` columns, so any row can be rescaled by hand without a
rerun. See `DATA_DICTIONARY.md`.

---

## Column names are moving

`v0.3` writes both the canonical names and the legacy aliases, with identical
values. The aliases are removed in `v0.4`.

| Legacy | Canonical | Unit |
|---|---|---|
| `D_counts` | `congested_passed_volume_counts_veh` | veh |
| `D_speed` | `congested_passed_volume_speed_veh` | veh |
| `DC_hours` | `capacity_equivalent_hours_counts` | **h** |
| `V_counts` | `period_volume_counts_veh` | veh |
| `V_speed` | `period_volume_speed_veh` | veh |

`tests/test_units.py` fails if the two ever diverge.

---

## Conventions that will change your numbers if you get them wrong

- **`D_counts` and `D_speed` are vehicle counts, not the rate-based demand `D`
  in `D/C`.**
- **`DC_hours` has units of hours.** It is congested passed volume divided by an
  hourly rate — a duration, not a dimensionless ratio.
- **Flows are full cross-section**, all lanes. `capacity_vphpl` is the only
  per-lane column.
- **The profile is a 24-hour cycle.** A run below cutoff at both 23:55 and 00:00
  is one episode, stitched before the 30-minute minimum is applied.
- **AM is 06:00–09:00**, MD 09:00–15:00, PM 15:00–19:00, NT 19:00–06:00.
