"""Leave-one-out validation and self-check for main.py.

Run it against the kit's practice input:

    MAKEFUN_INPUT_DIR=/path/to/kit/input python3 validate.py

It does two things:

1. Asserts main.py's own output on every case the input directory holds is well formed under the
   contest's rules (23 rows, hours 2..24 once each, five finite non-decreasing quantiles in
   (0, 1e9], at most 65,536 bytes) and byte-identical over two runs.
2. Scores the model by leave-one-out over the comparables carried in the case files: each
   comparable is forecast from the other comparables alone and scored with the contest's pinball
   loss, against the house baseline on the same launches.
"""

import json
import math
import os
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as entry

KIT = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
LEVELS = entry.LEVELS
Z = entry.Z
BASE_Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
BASE_SIGMA = 0.15


def pinball(y, q, tau):
    d = math.log(max(y, 1.0)) - math.log(q)
    return 2.0 * max(tau * d, (tau - 1.0) * d)


def check_outputs(cases):
    """The contest's own shape rules, plus determinism over two runs."""
    runs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            entry.OUTPUT_DIR = Path(tmp)
            entry.INPUT_DIR = KIT
            entry.main()
            runs.append({p.name: p.read_bytes() for p in sorted(Path(tmp).glob("*.out"))})
    assert runs[0] == runs[1], "two runs differ: the entry is not deterministic"
    assert runs[0], f"no output written for the cases in {KIT}"

    for name, raw in runs[0].items():
        assert len(raw) <= 65536, f"{name} is {len(raw)} bytes, over the 65,536 limit"
        doc = json.loads(raw)
        assert set(doc) == {"hours"}, f"{name} has keys {sorted(doc)}, not just 'hours'"
        rows = doc["hours"]
        assert len(rows) == 23, f"{name} has {len(rows)} rows, not 23"
        assert sorted(r["hour"] for r in rows) == list(range(2, 25)), f"{name} is not hours 2..24"
        for r in rows:
            assert set(r) == {"hour", "q"}, f"{name} hour {r['hour']} has keys {sorted(r)}"
            q = r["q"]
            assert len(q) == 5, f"{name} hour {r['hour']} has {len(q)} quantiles"
            for v in q:
                assert isinstance(v, (int, float)) and math.isfinite(v), f"{name} hour {r['hour']}: {v}"
                assert 0 < v <= 1e9, f"{name} hour {r['hour']}: {v} out of (0, 1e9]"
            assert all(a <= b for a, b in zip(q, q[1:])), f"{name} hour {r['hour']} not sorted: {q}"
    print(f"shape + determinism: {len(runs[0])} case(s) OK")
    return runs[0]


def leave_one_out(case):
    """Score every usable comparable as if it were the case, from the others alone."""
    pool = entry.analogs(case)
    if len(pool) < 5:
        return None
    rows = []
    for i, (name, curve, runup, roll, pc, first) in enumerate(pool):
        others = pool[:i] + pool[i + 1:]
        ws = entry.weights(others, (first, runup, roll, pc))
        for h in range(2, 25):
            if h not in curve:
                continue
            y = max(first * math.exp(curve[h]), 1.0)
            pairs = [(others[j][1][h], ws[j]) for j in range(len(others)) if h in others[j][1]]
            if not pairs:
                continue
            med = entry.weighted_quantile(pairs, 0.5)
            lo = entry.weighted_quantile(pairs, 0.10)
            hi = entry.weighted_quantile(pairs, 0.90)
            sigma = max((hi - lo) / 2.5631031310892007, 1e-6) * entry.P["k_sg"]
            sigma = max(sigma, entry.P["floor"] * math.sqrt(h - 1))
            sigma = min(sigma, entry.P["cap"])
            mu = med * entry.P["k_mu"]
            qs = sorted(entry.clamp(first * math.exp(mu + z * sigma)) for z in Z)
            base = [first * math.exp(z * BASE_SIGMA * math.sqrt(h - 1)) for z in BASE_Z]
            rows.append((name, first, y, qs, base))
    return rows


def summarise(rows, keep=lambda name, first, y: True):
    mine, house, cover, miss = [], [], [], []
    for name, first, y, qs, base in rows:
        if not keep(name, first, y):
            continue
        for tau, q, b in zip(LEVELS, qs, base):
            mine.append(pinball(y, q, tau))
            house.append(pinball(y, b, tau))
        cover.append(1.0 if qs[0] <= y <= qs[4] else 0.0)
        miss.append(abs(math.log(y) - math.log(qs[2])))
    if not mine:
        return None
    return (statistics.fmean(mine), statistics.fmean(house),
            statistics.fmean(cover), 100.0 * (math.exp(statistics.fmean(miss)) - 1.0))


def main():
    cases = sorted(KIT.glob("*.in"))
    assert cases, f"no *.in cases under {KIT}; set MAKEFUN_INPUT_DIR to the kit's input/"
    check_outputs(cases)

    case = json.loads(cases[0].read_text(encoding="utf-8"))
    rows = leave_one_out(case)
    assert rows, "too few usable comparables in the case to validate against"

    everything = summarise(rows)
    # GTA VI is a very large launch that has already surged by hour 1: score that cohort apart.
    big = summarise(rows, keep=lambda name, first, y: first >= 20000)
    for label, r in (("all comparables", everything), ("large launches (hour 1 >= 20k)", big)):
        if r is None:
            continue
        print(f"{label}: loss {r[0]:.6f} vs house baseline {r[1]:.6f} "
              f"(coverage {r[2]:.3f}, typical miss {r[3]:.1f}%)")

    assert big is not None and big[0] < big[1], (
        f"the model does not beat the house baseline on large launches: {big[0]:.6f} >= {big[1]:.6f}")
    print("OK")


if __name__ == "__main__":
    main()
