# shot-take-optimisation

An analytic calculator for the question *what stakes should I be playing?*

The premise: stake selection has only two covariates — the **expected value** of a
configuration and the **probability it ruins you**. The rule is one line: take the
highest-EV configuration available that stays inside your risk tolerance. Most of
what poker treats as separate considerations ("am I ready", "I'm a 100NL reg", the
20/30/50-buy-in rules) is either an input to one of those two numbers, or a proxy
standing in for one — and once you can compute them directly, the proxy is
redundant.

This repo computes them directly, in closed form.

## The four inputs

Everything lives in [`config.toml`](config.toml), and everything comes out in euros.

1. **Bankroll**, in euros.
2. **Tables played simultaneously.**
3. **Win rate and standard deviation for each stake you have data on**, in bb/100.
4. **Risk-of-ruin tolerance** — a constraint, not a display setting. It decides
   which stakes are in bounds at your current roll.

Every number in the shipped config is a placeholder. Replace them before reading
anything into the output — a made-up standard deviation produces a confident,
wrong answer, and nothing downstream will flag it.

## Running it

Needs Python 3.11+ (for `tomllib`) and, for the charts only, matplotlib.

```
py -m shotopt report                    # the main table
py -m shotopt stake 200NL               # one stake in detail
py -m shotopt kelly                     # the fractional-Kelly trade-off
py -m shotopt report --charts           # also write PNGs to output/

py -m shotopt report --bankroll 12000   # sweep an input without editing the file
py -m unittest discover -s tests -t .   # the test suite
```

`--bankroll`, `--tables`, `--ruin-tolerance` and `--kelly-fraction` work before or
after the subcommand.

Sample output:

```
stake         EUR/hr   buy-ins       ruin         roll for tol.    Kelly roll    P(-50%)
----------------------------------------------------------------------------------------
50NL              32       100      0.00%  OK      1,484 (30bi)         1,289       0.0%
100NL             50        50      0.15%  OK      3,543 (35bi)         3,078       3.9%
200NL             63        25     11.53%  NO     10,658 (53bi)         9,257      34.0%

VERDICT: 100NL - the highest EUR/hour that stays inside 1.00% ruin
         200NL needs EUR 10,658 - another EUR 5,658.
```

## The maths

All per 100 hands, in big blinds. μ = win rate, σ = standard deviation, B =
bankroll in bb. Derivations and provenance in [`docs/theory.md`](docs/theory.md).

| Quantity | Formula |
|---|---|
| Risk of ruin, fixed stake | `R = exp(-2μB / σ²)` |
| Bankroll for a ruin tolerance | `B = -σ² ln(R) / 2μ` |
| Full-Kelly bankroll for a stake | `B* = σ² / μ` |
| Bankroll at Kelly fraction k | `B*/k` |
| Full-Kelly growth rate | `g = μ² / 2σ²` |
| Growth at fraction k | `k(2-k) · g` |
| Variance at fraction k | `k²` × full |
| P(Kelly bettor ever hits fraction x) | `x^(2/k - 1)` |
| Win-rate standard error | `σ / √(hands/100)` |
| Hands for ±e precision | `n = 100(zσ/e)²` |

Two results worth internalising, both of which fall straight out of the above:

- **At the full-Kelly bankroll, risk of ruin is e⁻² ≈ 13.5% — always.** It does not
  depend on your win rate or your variance; the two cancel. That single constant is
  the cleanest argument against full Kelly.
- **Half Kelly keeps three quarters of the growth for a quarter of the variance**,
  and at half Kelly a 50% drawdown drops from a coin flip to 12.5%. Growth is
  symmetric about k=1 but risk is not, so **overbetting is far worse than
  underbetting** — and since your win rate is an estimate, shading down is the cheap
  side to be wrong on.

## Two assumptions, stated rather than buried

Both default to zero — the textbook case. Any non-zero value is a number you chose
to believe, not something this repo measured.

- **`table_correlation`** inflates the standard deviation to
  `σ√(1 + ρ(tables-1))`. The ruin formula assumes hands arrive one at a time;
  playing twelve at once puts them in flight together, and they are correlated
  within a session. How correlated is an open question.
- **`winrate_haircut_bb_per_table`** charges bb/100 per table beyond the first, for
  attention spread thin. Real in principle, unmeasured here.

Two more limits worth knowing, which no config knob fixes:

- **The ruin numbers assume you play that stake at a fixed size forever.** They are
  an upper bound on real risk — in practice you would move down. That makes them
  the right *constraint* and the wrong *forecast*.
- **`ruin.drawdown_probability` and `kelly.rescaled_drawdown_probability` are
  different laws**, for a fixed-stake grinder and a continuously-rescaling Kelly
  bettor respectively. Real poker sits between them: you rescale, but in discrete
  jumps when you change stake. Don't mix them up.

## What this is not (yet)

The closed forms above are deliberately step one. They cannot price the thing that
actually makes shot-taking interesting: a **continuous mix of tables across
stakes** (10× 100NL + 2× 200NL), governed by a **policy** — move up through one
threshold, down through another, with hysteresis between them — where the EV cost
of a forced move-down is *paid* by the simulation rather than assumed.

That is a Monte Carlo, and it comes next. This repo is what it will be validated
against: a simulation that disagrees with these formulas in the simple case is a
simulation with a bug. The maths modules take and return plain floats precisely so
the sim can import them as its oracle.

## Layout

```
config.toml          the four inputs
shotopt/
  config.py          load + validate
  kelly.py           sizing, growth, the fractional trade-off
  ruin.py            risk of ruin, drawdown, effective sigma
  estimation.py      standard errors, intervals, shaded win rates
  rates.py           bb/100 -> EUR/hour
  analysis.py        the only module that knows about both config and maths
  charts.py          five PNGs
  cli.py             the command line
tests/               54 tests, stdlib unittest, no dependencies
docs/theory.md       derivations and where they come from
```
