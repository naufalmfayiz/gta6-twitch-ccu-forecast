# gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/naufalmfayiz/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/naufalmfayiz/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A weighted analog-shape forecaster for Grand Theft Auto VI's launch-day Twitch audience: given
everything recorded up to the end of 2026-11-19's first UTC hour, it writes five quantiles of the
concurrent-viewer count for each of hours 2 to 24.

## The idea

A launch day's audience curve is mostly the same curve every time, scaled: the count sags through
the small UTC hours, climbs through the European and American evenings, and peaks late. What
differs between launches is *which* curve — a game that unlocks at midnight local time, rolling
westward, does not look like one that unlocks worldwide at a single instant, and a console-only
release does not look like one with PC in the mix.

So the forecast for hour h is hour 1's print times the distribution, over past launches, of that
launch's own hour-h / hour-1 ratio — weighted toward the launches that look like this one:

- the same unlock style (rolling midnight-local vs a single global unlock),
- the same platform mix (console-only vs PC in the mix),
- a similar hour-1 scale, on a log-viewer Gaussian kernel,
- a similar run-up shape in the 1, 2, 3, 4, 6 and 12 hours before the day began.

The median of that weighted distribution is the median forecast; its weighted 10–90 band, read as a
normal's, is the spread, floored at a random walk of 0.13 log units per square-root hour and capped
at 1.5. Every comparable keeps a small floor weight, so no hour is ever left without a forecast.

GTA VI unlocks at midnight local time country by country and ships on PS5 and Xbox Series X|S only,
so the weighting leans on the rolling console launches in the pool — Elden Ring, Ghost of Yōtei,
The Last of Us Part II, Final Fantasy VII Rebirth, Tears of the Kingdom, the Call of Duty releases —
and away from the single-unlock PC launches whose curves spike on a different clock.

## Validation

`validate.py` scores the model by leave-one-out over the comparables the case files carry: each
launch is forecast from the other launches alone, with the contest's own pinball loss on the log
scale, against the house baseline on the same launches.

```
MAKEFUN_INPUT_DIR=/path/to/kit/input python3 validate.py
```

| cohort | this model | house baseline | 90% coverage |
|---|---|---|---|
| all comparables | 0.376 | 0.930 | 0.87 |
| large launches (hour 1 ≥ 20k) | **0.230** | 0.321 | 0.90 |

The second row is the one that matters: GTA VI is a very large launch that has already surged well
before hour 1 ends, so the small and slow-burn launches in the pool (Silksong, Helldivers 2,
ARC Raiders) are a different problem. The same script also asserts the output's shape against the
contest's rules and that two runs are byte-identical.

## Running it

```
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network, no randomness, no clock reads: two runs on the same
input write the same bytes. A full practice run takes under 0.1 s.

## License

MIT. See LICENSE.

---

<sub>Entered on [make.fun](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
