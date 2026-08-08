# shot-take-optimisation

**What distribution of stakes should my tables be at?**

Two covariates decide it: what a configuration earns per hour, and the chance it
ruins you. The rule is one line — take the highest-earning mix that stays inside
your risk tolerance. "Am I ready for 200NL", "I'm a 100NL reg", the 20/30/50
buy-in conventions: all either inputs to those two numbers or proxies for them,
and redundant once you compute them directly.

Picking a single stake for all your volume is a false constraint anyway. Volume is
already divisible across tables, so 12× 100NL can be 10× 100NL + 2× 200NL, and
risk moves smoothly with the dial instead of jumping when you "take a shot".

The output is two things:

1. **A stake screen** — each stake priced alone, with the redundant ones ruled out.
2. **The efficient frontier** — every mix nothing else beats on both axes, as a
   table and a chart.

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

Edit `config.toml`, then run it. There is no build step and nothing to rebuild —
the config is read fresh on every run.

```
run.bat                     THE ANSWER: both tables printed, both as CSV, plus the chart
run.bat mix                 the same, minus the chart
run.bat mix --bankroll 12000    sweep an input without editing the file
run.bat --output results        put the files somewhere else

run.bat report              secondary: per-stake detail if all volume went to one stake
run.bat stake 200NL         secondary: one stake, with its confidence interval
```

Everything lands in `output\`:

| file | what |
|---|---|
| `stake_screen.csv` | one row per stake, including the ruled-out ones and why |
| `frontier.csv` | one row per undominated mix, with a table-count column per stake |
| `frontier.png` | the chart |

**Bare `run.bat` is the whole job**, so nothing in `output\` can be stale against
the config. The CSVs are written on every `mix` run (they're free); only the chart
needs `--charts`, which the bare invocation passes for you.

The CSVs keep full precision on the risk columns — rounding ruin to the two
decimals the terminal shows would collapse every safe mix to `0.00%` and make the
column useless for sorting.

`run.bat` is a batch file — run it directly (`.\run.bat` in PowerShell), not
through Python. It finds an interpreter itself: this repo's `.venv`, else a
`nemesis-mvp` venv next door, else `py`.

### If you want `python` to work

On a stock Windows box `python` is a Microsoft Store stub that installs nothing
and helps less; only `py` resolves to a real interpreter. Activating this repo's
venv fixes that for the shell you're in:

```
.\.venv\Scripts\Activate.ps1     # now `python` means this repo's interpreter
python run.py mix
python -m shotopt mix
pytest                           # the test suite
```

### First-time setup, if `.venv` is missing

It is gitignored, so a fresh clone needs it once:

```
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Only the charts and the test runner need those. The maths and every text command
are pure standard library on Python 3.11+ (3.11 for `tomllib`).

`--bankroll`, `--tables`, `--ruin-tolerance` and `--kelly-fraction` work before or
after the subcommand. `mix` is the default when no subcommand is given.

Sample output:

```
STEP 1 - STAKE SCREEN   (if all 12 tables were at one stake)

  stake        EUR/hr    EUR/100   sd EUR/100   verdict
  50NL             32       3.50           48   keep
  100NL            50       5.50           92   keep
  200NL            63       7.00          180   keep
  400NL            72       8.00          352   keep
  600NL            54       6.00          528   REDUNDANT - 200NL earns more at lower variance
  1KNL             45       5.00          880   REDUNDANT - 100NL earns more at lower variance

STEP 2 - EFFICIENT FRONTIER   (37 undominated mixes over 4 stakes)

    EUR/hr       ruin   P(-50%)  mix
        50      0.00%      0.0%  12x 100NL
        ...
        69      0.73%      8.5%  4x 200NL + 8x 400NL  <- BEST INSIDE TOLERANCE
        70      1.00%     10.0%  3x 200NL + 9x 400NL
        72      2.08%     14.4%  12x 400NL
```

## What the two steps mean

**The screen.** A stake is redundant when another earns at least as much per 100
hands *and* carries no more variance. Both halves matter — a stake that earns less
but is also less volatile is a genuine low-risk option, which is why 50NL survives
at the bottom of the frontier. A higher stake with a worse *euro* win rate is the
case worth catching: more rake and more variance for less money.

Removing them cannot change the answer. Every allocation using a dominated stake
is beaten on both axes by moving those tables to the dominator, so it can never
reach the frontier — asserted in the tests, which is what makes this a pruning
step rather than an approximation. One exception, handled: if the dominating stake
has a binding `max_tables`, it cannot absorb the tables, so nothing is ruled out.

**The frontier.** Of the hundreds of possible mixes, most are beaten on *both*
axes by some other mix — those are dominated and never worth picking. What's left
is the menu: the mixes where the only way to earn more is to accept more risk.
Your tolerance picks the row. Nothing off the list is worth considering at any
tolerance.

Its *shape* is the useful part. On the sample above, going from €50 to €72/hr — a
44% raise — is bought with a very steep climb in ruin, and the top of the ladder
buys almost nothing over the middle of it.

## The maths

Per 100 hands. μ = win rate bb/100, σ = standard deviation bb/100, vₛ = big blind
in euros, B = bankroll. Derivations in [`docs/theory.md`](docs/theory.md).

| Quantity | Formula |
|---|---|
| Mix mean, euros per 100 hands | `Σ (nₛ/T) · μₛ · vₛ` |
| Mix variance, euros² per 100 | `Σ (nₛ/T) · σₛ² · vₛ²` |
| Risk of ruin | `R = exp(-2 · mean · B / var)` |
| P(ever losing fraction x) | same, with B scaled to `x·B` |
| Win-rate standard error | `σ / √(hands/100)` |

Set every table to one stake and the mix collapses exactly to that stake's own
single-stake numbers — tested, and worth having since the two paths compute in
different units.

### On the Kelly fraction

Fixed at **k = 0.5**, half Kelly, and there's no reason to move it.

Full Kelly is the exposure that maximises long-run growth, and it's far too hot to
play: at the full-Kelly bankroll your risk of ruin is e⁻² ≈ **13.5% regardless of
your win rate or variance** (they cancel), and a 50% drawdown is a coin flip.
Halving it keeps **three quarters of the growth for a quarter of the variance**.
Growth is symmetric about the optimum but risk isn't, so being under is cheap and
being over is not — and with a win rate you only ever *estimate*, you shade down.

It plays no part in the mix answer; only `report` and `stake` use it.

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

## Why the answer is exact

There is no simulation here and none is needed. Tables deal independent hands, so
the aggregate mean and variance above are closed-form, and the allocation space is
small enough to enumerate in full — 12 tables over 5 stakes is 1,820 mixes. The
optimum is found by brute force. No sampling, no convergence question, no search
heuristic that might have missed something.

Set `max_tables` on a stake if you can't realistically get that many seats. It's
the constraint most likely to bind in practice, and without it the optimiser will
happily seat you at four 400NL tables that don't exist.

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
  mix.py             the answer: screen the stakes, enumerate and score every mix
  ruin.py            risk of ruin, drawdown, effective sigma
  kelly.py           sizing and growth (used by report/stake only)
  estimation.py      standard errors, intervals, shaded win rates
  rates.py           bb/100 -> EUR/hour
  analysis.py        the only module that knows about both config and maths
  charts.py          the frontier chart
  export.py          CSV copies of the two printed tables
  cli.py             the command line
tests/               98 tests, no dependencies (pytest or stdlib unittest)
docs/theory.md       derivations and where they come from
```
