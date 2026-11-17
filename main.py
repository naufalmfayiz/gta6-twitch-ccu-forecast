"""gta6-twitch-ccu-forecast-01 entry: a weighted analog-shape forecaster.

The forecast for hour h is hour 1's print times the weighted distribution, over past launches, of
that launch's own hour-h / hour-1 ratio. Weights favour launches that look like this one: the same
unlock style (rolling midnight-local vs a single global unlock), the same platform mix, a similar
hour-1 scale, and a similar run-up shape in the hours before the day began. The quantiles come from
the weighted spread of those ratios, never narrower than a random walk and never wider than a cap.

Validated by leave-one-out over the kit's comparables (see validate.py in this repo): on the 25
large launches that resemble GTA VI, mean pinball loss 0.183 against the house baseline's 0.271.

Stdlib only, no network, deterministic: no randomness, no dict-order dependence, no clock reads.
"""

import json
import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]

# Tuned by leave-one-out on the kit's comparables; see validate.py.
P = {
    "roll_boost": 6.0,    # same unlock style (rolling midnight-local vs single global)
    "pc_boost": 2.0,      # same platform mix (console-only vs PC in the mix)
    "bw_scale": 0.8,      # bandwidth on |log(hour-1 scale ratio)|
    "bw_shape": 1.2,      # bandwidth on the run-up shape distance
    "nodata": 0.5,        # weight factor when a comparable has too little run-up to compare
    "wfloor": 0.03,       # every comparable keeps a little weight, so no hour is left empty
    "k_mu": 1.0,          # shrink on the median log-ratio
    "k_sg": 0.9,          # scale on the spread
    "floor": 0.13,        # spread never below this per sqrt(hour), in log units
    "cap": 1.5,           # spread never above this, in log units
}
# The run-up lags compared, in hours before the day's first hour.
LAGS = (1, 2, 3, 4, 6, 12)
MIN_LAGS = 3            # fewer overlapping lags than this and the shape term is skipped
MIN_HOURS = 20          # a comparable needs this many of hours 2..24 to join the pool
MAX_VIEWERS = 1e9       # the contest's ceiling on a quantile


def parse_hour(text):
    """ISO-8601 UTC instant -> whole hours since the Unix epoch. Deterministic, no tz database."""
    year = int(text[0:4])
    month = int(text[5:7])
    day = int(text[8:10])
    hour = int(text[11:13])
    # Days since 1970-01-01 by the civil-from-days algorithm (Howard Hinnant's), exact for any date.
    y = year - (1 if month <= 2 else 0)
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe - 719468
    return days * 24 + hour


def hourly_series(points, day_start, key="from"):
    """{hour offset from day_start: viewers}, offset 0 being the day's first hour."""
    base = parse_hour(day_start)
    out = {}
    for p in points:
        v = p.get("viewers")
        if v is None:
            continue
        out[parse_hour(p[key]) - base] = v
    return out


def case_series(case):
    """The target's own hours, from history_hourly where it has them, else from the raw history."""
    day_start = case["day_start"]
    rows = case.get("history_hourly") or []
    if rows:
        return hourly_series(rows, day_start, "from")
    base = parse_hour(day_start)
    buckets = {}
    for p in case.get("history") or []:
        v = p.get("viewers")
        if v is None:
            continue
        buckets.setdefault(parse_hour(p["at"]) - base, []).append(v)
    return {k: statistics.fmean(v) for k, v in buckets.items()}


def is_rolling(text):
    low = (text or "").lower()
    return "midnight local" in low or "rolling" in low


def has_pc(comp):
    return "PC" in (comp.get("platforms") or "") or "Steam" in (comp.get("unlock") or "")


def run_up(series, first):
    """log(viewers / hour-1 print) at each run-up lag the series has."""
    out = {}
    for k in LAGS:
        v = series.get(-k)
        if v is not None and v > 0 and first > 0:
            out[k] = math.log(v / first)
    return out


def shape_distance(a, b):
    keys = sorted(k for k in a if k in b)
    if len(keys) < MIN_LAGS:
        return None
    return math.sqrt(statistics.fmean([(a[k] - b[k]) ** 2 for k in keys]))


def weighted_quantile(pairs, tau):
    """Weighted quantile, interpolating on cumulative weight at each point's midpoint."""
    pairs = sorted(pairs)
    total = math.fsum(w for _, w in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    target = tau * total
    cum = 0.0
    prev_v, prev_c = pairs[0][0], 0.0
    for v, w in pairs:
        mid = cum + w / 2.0
        if mid >= target:
            if mid == prev_c:
                return v
            return prev_v + (target - prev_c) / (mid - prev_c) * (v - prev_v)
        prev_v, prev_c = v, mid
        cum += w
    return pairs[-1][0]


def analogs(case):
    """Each usable comparable as (name, curve, run-up, rolling, pc, hour-1 print)."""
    out = []
    for comp in case.get("comparables") or []:
        series = hourly_series(comp.get("hourly") or [], comp["day_start"], "from")
        first = series.get(0)
        if not first or first <= 0:
            continue                                  # not a launch day we can anchor on hour 1
        curve = {}
        for h in range(2, 25):
            v = series.get(h - 1)
            if v is not None:
                curve[h] = math.log(max(v, 1.0) / first)
        if len(curve) < MIN_HOURS:
            continue                                  # too sparse to speak for a whole day
        out.append((comp["name"], curve, run_up(series, first),
                    is_rolling(comp.get("unlock")), has_pc(comp), float(first)))
    out.sort(key=lambda row: row[0])                  # name order, so two runs weigh identically
    return out


def weights(pool, target):
    """One weight per comparable: how much this launch looks like the case being forecast."""
    t_first, t_runup, t_roll, t_pc = target
    out = []
    for _name, _curve, runup, roll, pc, first in pool:
        w = 1.0
        if roll == t_roll:
            w *= P["roll_boost"]
        if pc == t_pc:
            w *= P["pc_boost"]
        w *= math.exp(-0.5 * (abs(math.log(first / t_first)) / P["bw_scale"]) ** 2)
        d = shape_distance(runup, t_runup)
        w *= P["nodata"] if d is None else math.exp(-0.5 * (d / P["bw_shape"]) ** 2)
        out.append(w + P["wfloor"])
    return out


def clamp(x):
    """A quantile the contest will accept: finite, at least 1 viewer, at most a billion."""
    if not math.isfinite(x):
        return 1.0
    return min(max(x, 1.0), MAX_VIEWERS)


def forecast_case(case, name):
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    first_row = next((k for k in case["known"] if k["hour"] == 1), None)
    if first_row is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first_row["viewers"]))

    notes = case.get("notes") or ""
    own = case_series(case)
    target = (p1, run_up(own, p1), is_rolling(notes), has_pc({"platforms": notes}))

    pool = analogs(case)
    ws = weights(pool, target)

    hours = []
    for row in case["forecast"]:
        h = row["hour"]
        pairs = [(pool[i][1][h], ws[i]) for i in range(len(pool)) if h in pool[i][1] and ws[i] > 0]
        if not pairs:
            pairs = [(0.0, 1.0)]                      # no analog reaches this hour: hold at hour 1
        med = weighted_quantile(pairs, 0.5)
        lo = weighted_quantile(pairs, 0.10)
        hi = weighted_quantile(pairs, 0.90)
        # the weighted 10-90 band read as a normal's, then floored and capped
        sigma = max((hi - lo) / 2.5631031310892007, 1e-6) * P["k_sg"]
        sigma = max(sigma, P["floor"] * math.sqrt(max(h - 1, 1)))
        sigma = min(sigma, P["cap"])
        mu = med * P["k_mu"]
        qs = sorted(clamp(p1 * math.exp(mu + z * sigma)) for z in Z)
        hours.append({"hour": h, "q": [round(q, 2) for q in qs]})
    hours.sort(key=lambda r: r["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        out = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
