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

Edit `config.toml`, then run it — there is no build step, the config is read fresh
every time.

```
run.bat                     THE ANSWER: best split of tables across stakes
run.bat report              per-stake table, if all volume went to one stake
run.bat stake 200NL         one stake in detail
run.bat kelly               the fractional-Kelly trade-off
run.bat mix --charts        also write PNGs to output/

run.bat mix --bankroll 12000    sweep an input without editing the file
```

`run.bat` finds an interpreter for you (this repo's `.venv` if it exists, else the
`nemesis-mvp` one next door, else `py`). Equivalent, if you'd rather be explicit:

```
python run.py mix
python -m shotopt mix
python -m unittest discover -s tests -t .    # the test suite
```

`--bankroll`, `--tables`, `--ruin-tolerance` and `--kelly-fraction` work before or
after the subcommand. `mix` is the default when no subcommand is given.

Sample output:

```
1,820 ways to split 12 tables across 5 stakes; 36 stay inside 1.00% ruin.

BEST MIX
  10x 100NL + 2x 200NL
  52 EUR/hr   ruin 0.99%   P(-50%) 9.9%
  Against the best single-stake option (12x 100NL, 50 EUR/hr): +2 EUR/hr, +5%.

ONE MORE TABLE UP
  10x 100NL + 1x 200NL + 1x 400NL
  buys +1 EUR/hr, costs +4.49% ruin -> OUTSIDE tolerance
```

followed by the efficient frontier — every mix nothing else beats on both axes.

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

## The mix, and why it needs no simulation

Picking one stake for all your volume is a false constraint — volume is already
divisible across tables, so the real decision variable is the **share of
simultaneous tables at each stake**. 12× 100NL can be 10× 100NL + 2× 200NL, and
risk scales smoothly with the dial instead of jumping when you "take a shot".

Tables deal independent hands, so a mix has a computable mean and variance per 100
hands, in euros:

    mean = Σ (nₛ/T) · μₛ · vₛ
    var  = Σ (nₛ/T) · σₛ² · vₛ²

with nₛ tables at stake s, T tables total, vₛ the big blind in euros. Both are in
euros, so the ordinary ruin formula applies to the aggregate directly. Set every
table to one stake and it collapses *exactly* to that stake's own row in `report` —
asserted in the tests, since the two are computed by different routes (big blinds
vs euros) and a unit error would show up there.

So the optimum is found by **enumerating every allocation** and taking the highest
EUR/hour inside tolerance. No sampling, no convergence question, no search
heuristic: 12 tables over 5 stakes is 1,820 allocations, and the answer is exact.

Set `max_tables` on a stake if you cannot realistically get that many seats — it is
the constraint most likely to bind, and without it the optimiser will happily
allocate eight tables to a stake that never has eight good games running.

## What this is not (yet)

Everything above is a **static** snapshot at one bankroll. The dynamic problem is
not solved: the roll moves while you play it, so the right mix is a function of the
bankroll you have *now*, and the object to optimise is a **policy** — move up
through one threshold, down through another, with hysteresis between them so paths
near the boundary don't thrash. That is where the EV cost of a forced move-down
gets *paid* by the model rather than assumed, and it needs a Monte Carlo.

This repo is what that simulation will be validated against: one that disagrees
with these formulas in the static case has a bug. The maths modules take and return
plain floats precisely so the sim can import them as its oracle.

## Layout

```
config.toml          the four inputs
shotopt/
  config.py          load + validate
  kelly.py           sizing, growth, the fractional trade-off
  ruin.py            risk of ruin, drawdown, effective sigma
  estimation.py      standard errors, intervals, shaded win rates
  rates.py           bb/100 -> EUR/hour
  mix.py             enumerate and score every table allocation
  analysis.py        the only module that knows about both config and maths
  charts.py          six PNGs
  cli.py             the command line
tests/               78 tests, stdlib unittest, no dependencies
docs/theory.md       derivations and where they come from
```
