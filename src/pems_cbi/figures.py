"""The one figure: speed-inferred D and V against the measured counts.

Both axes are the same quantity in the same unit, so the diagonal is the whole
story -- a point on the line means flow inferred from speed alone reproduced
the measured vehicle count for that link and period.

Log axes, because the values span two orders of magnitude (D runs 357 to
42 375 vehicles); on linear axes the small links collapse into the corner and
the eye reads only the large ones.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Colourblind-safe, and distinguishable in greyscale by lightness order.
PERIOD_COLOUR = {"AM": "#0173b2", "MD": "#de8f05", "PM": "#029e73", "NT": "#cc78bc"}
BAND = 0.20     # the +/-20 % guide band


def _panel(ax, frame: pd.DataFrame, counts: str, speed: str, title: str,
           subtitle: str, note: str) -> None:
    lo = min(frame[counts].min(), frame[speed].min()) * 0.7
    hi = max(frame[counts].max(), frame[speed].max()) * 1.4
    line = np.array([lo, hi])

    ax.fill_between(line, line * (1 - BAND), line * (1 + BAND),
                    color="0.5", alpha=0.13, lw=0, zorder=0,
                    label=f"±{BAND:.0%}")
    ax.plot(line, line, color="0.35", lw=1.0, zorder=1)

    for period, colour in PERIOD_COLOUR.items():
        sub = frame[frame["period"] == period]
        if sub.empty:
            continue
        ax.scatter(sub[counts], sub[speed], s=13, c=colour, alpha=0.72,
                   linewidths=0, zorder=2, label=f"{period}  (n={len(sub)})")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_xlabel(f"{title} from measured flow  [veh]")
    ax.set_ylabel(f"{title} from speed via S3  [veh]")
    ax.set_title(f"{title}   —   {subtitle}", loc="left", fontsize=11, pad=8)
    ax.text(0.035, 0.965, note, transform=ax.transAxes, va="top", ha="left",
            fontsize=8.5, linespacing=1.5,
            bbox=dict(boxstyle="round,pad=0.45", fc="white", ec="0.8", lw=0.7))
    ax.grid(True, which="major", lw=0.4, color="0.85")
    ax.grid(True, which="minor", lw=0.25, color="0.92")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower right", frameon=False, fontsize=8.5,
              handletextpad=0.4, borderaxespad=0.8)


def _note(frame: pd.DataFrame, err: str) -> str:
    e = frame[err].dropna()
    inside = (e.abs() <= BAND * 100).mean() * 100
    return (f"n = {len(e)}\n"
            f"MAPE = {e.abs().mean():.1f} %\n"
            f"median bias = {e.median():+.1f} %\n"
            f"within ±{BAND:.0%} = {inside:.0f} %")


def build(table: pd.DataFrame, out_path: Path) -> Path:
    """Two panels: D over the congested bins, V over the whole period."""
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 6.4))

    d = table[table["D_err"].notna()]
    _panel(axes[0], d, "D_counts", "D_speed", "D",
           "below-cutoff bins only", _note(d, "D_err"))
    _panel(axes[1], table, "V_counts", "V_speed", "V",
           "every bin of the period", _note(table, "V_err"))

    weekdays = int(table["weekdays_averaged"].median())
    fig.suptitle("Speed-inferred vehicle counts against measured PeMS flow",
                 x=0.055, y=0.975, ha="left", fontsize=13.5)
    fig.text(0.055, 0.918,
             f"Ten California corridor-directions, "
             f"{table.groupby(['corridor', 'link_id']).ngroups} links, "
             f"average weekday over {weekdays} weekdays. "
             f"Capacity source: {table['capacity_source'].iloc[0]}.",
             ha="left", fontsize=9.5, color="0.35")

    # aspect="equal" fixes the axes box, so let savefig crop to the
    # real extent rather than trying to guess a rect that fits the labels.
    fig.tight_layout(rect=(0.01, 0.0, 0.99, 0.885))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=170, bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)
    return out_path
