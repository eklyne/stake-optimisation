# stake-optimisation

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

Everything lives in [`config.toml`](config.toml).

1. **Bankroll**, in your display currency (see below).
2. **Tables played simultaneously.**
3. **Win rate and standard deviation for each stake you have data on**, in bb/100.
4. **Risk tolerance** — a constraint, not a display setting. It decides which
   stakes are in bounds at your current roll, and it comes in two shapes.

Every number in the shipped config is a placeholder. Replace them before reading
anything into the output — a made-up standard deviation produces a confident,
wrong answer, and nothing downstream will flag it.

### Two ways to set the risk tolerance

The `[risk]` block picks one. Both sets of numbers are read either way, because
the deck draws both frontier charts whichever rule binds.

```toml
[risk]
mode = "both"                  # "ruin" | "downswing" | "both"
ruin_tolerance = 0.0001        # P(ever bust) <= 0.01%
downswing_amount = 10000       # ...and: no more than a 1% chance
downswing_hands = 1000000      #    of a 10,000 fall
downswing_probability = 0.01   #    within 1M hands
```

**`mode = "ruin"`** is `P(the bankroll ever reaches zero) ≤ tolerance`. Analytic,
instant, and the classic framing. Its weakness is that it is an *all-time,
play-forever* number that treats every mix which survives as equally comfortable
— a mix that halves your roll twice a year and grinds it back counts as safe.

**`mode = "downswing"`** is `P(a fall of X or worse within Y hands) ≤ p`. What a
losing stretch actually feels like, over a horizon you can picture. **Peak to
trough** — measured from whatever high the roll had reached, not from where you
started. There is no closed form for it (given unlimited time it grows without
bound), so each candidate costs a simulation and `mix` takes a few seconds behind
a progress bar. It is much the stricter of the two on real inputs.

**`mode = "both"`** requires a mix to clear both bars, so the stricter one
decides — and which one that is changes on its own as the roll moves. Ruin binds
when the bankroll is small and falls away to nothing as it grows, at which point
the downswing rule takes over. You stop having to work out which framing is the
live one today, and the verdict line names the leg that bound:

```
Chosen: 2x 50NL + 10x 200NL runs a GBP 9,969 worst fall at 1%
over 1,000,000 hands, against a limit of GBP 10,000.
Both rules applied - ruin 6.2e-16 against a 0.01% bar (11 decades of room);
downswing GBP 9,969 against GBP 10,000 (GBP 31 of room).
```

They are not two spellings of one constraint. On a £40k bankroll a 0.01% ruin bar
happily admits a mix running a **£33,600** peak-to-trough fall: ruin asks only
whether you survive, and a fall that deep leaves you solvent and finished.

The bankroll is required in every mode: every chart needs a starting point, and
risk of ruin is reported alongside whichever rule binds.

### Why the downswing search is affordable

A naive walk down a six-thousand-mix ladder would simulate the bold end one mix at
a time and never reach anything admissible. Two things prevent that, and the first
is exact rather than a heuristic:

- **An analytic floor.** Peak-to-trough drawdown is *pathwise* at least the fall
  below the starting point, and that one has a closed form
  (`ruin.loss_below_start_quantile`). So a mix whose analytic figure already breaks
  the limit certainly breaks the simulated one, and is rejected for free. On the
  shipped config this removes 5,295 of 6,188 mixes before any Monte Carlo runs —
  64 are actually simulated.
- **Deduplication on `(mean, variance)`**, which is the entire input to the
  simulation, so mixes agreeing on both share an answer by construction.

If the search ever does run out of budget (`mix.MAX_TOLERANCE_TESTS`) it says so
explicitly rather than returning "nothing clears your tolerance" — those are
different statements and conflating them sends you down a stake for no reason.

### Currency

The tables are EUR and the model computes in EUR end to end. The currency setting
is a display skin over that: money you **type** (bankroll, `downswing_amount`) is
read in it, and money you **read back** — terminal, charts, deck, CSVs — is shown
in it. Stake `bb_eur` values stay in euros, because that is what is written on the
table you sit at.

```toml
currency = "GBP"
fx_eur_per_unit = 1.16    # euros in ONE unit of the currency
```

The rate is a fixed constant you choose, never a live quote — a bankroll plan that
moved with spot would not be a plan, and rebuilding the deck would silently change
every figure on it. Omit both keys (or set `currency = "EUR"`) and nothing is
converted anywhere. bb/100 figures are never affected.

## Running it

Edit `config.toml`, then run it. There is no build step and nothing to rebuild —
the config is read fresh on every run.

```
run.bat                     THE ANSWER: tables printed, CSVs, chart and deck
run.bat mix                 the same, minus the chart and deck
run.bat mix --charts        add the chart only
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
| `frontier.png` | the frontier, priced in risk of ruin |
| `frontier_downswing.png` | the same frontier, priced in peak-to-trough downswing |
| `stake_optimisation.pptx` | the deck |
| `stake_optimisation_data.xlsx` | every number on the deck, in tabs you can pivot |

Money columns in the CSVs and the workbook carry the display currency in their
header (`per_hour_gbp`), so a column can never be read in the wrong unit.

### The data file

The deck and its workbook are a **pair**, written in one pass from one set of
objects — the workbook is built inside `deck.build` from the values the slides
already hold, so it cannot disagree with the deck it ships beside, and it costs no
extra simulation. Tabs:

| tab | what |
|---|---|
| `INDEX` | what is on each tab |
| `RUN` | every input the run actually used, CLI overrides included |
| `STAKES` | config inputs and screen verdict, per stake |
| `ALLOCATIONS` | **every** mix scored, flagged for frontier / best / current |
| `FRONTIER` | the undominated mixes, plus loss-below-start quantiles |
| `DOWNSWING` | median / 10% / 1% worst falls for the mixes the deck quotes |
| `LADDER` | the optimum re-solved at each bankroll growth step |
| `STEP_UP` | the two ways to move a table up, and what each costs |
| `SIM_FAN` | bankroll percentile bands over the horizon, per headline mix |
| `SIM_OUTCOMES` | where the headline mixes finish and how deep they dig |
| `WINRATE_CI` | the win-rate slide: modelled rate, rakeback, sample interval |

`ALLOCATIONS` is the one worth knowing about: the full cloud from the frontier
chart, so *"what would 8× 200NL + 4× 400NL have done"* is a filter rather than a
re-run.

### Two columns worth explaining

**`On tables`** is the money sitting in front of you at once, at a full 100bb
buy-in per seat — `Σ tables × 100bb`. Everything else in these tables is a *rate*
(per hour, per 100 hands) or a probability; this is the **stock** rather than the
flow, and it is the figure to hold against your bankroll. 12× 200NL puts £2,069 on
the table; 12× 1KNL puts £10,345, a quarter of a £40k roll, in play at once.

**Risk of ruin** is also quoted as odds against (`10,000/1`). Anything rarer than
a million to one collapses to `<1M/1` — the safe end of the ladder runs to 1e-129,
where the literal odds are a 130-digit integer and no decision turns on the
difference.

### The simulation charts

Plotted as **profit from start**, not bankroll: zero is where you began, so the
line reads as what you made rather than as a total carrying a constant offset.
Ruin then has a place on the axis — the red dotted barrier at minus the whole roll
— instead of being the invisible point where a total happens to reach nil.

**Bare `run.bat` is the whole job**, so nothing in `output\` can be stale against
the config. The CSVs are written on every `mix` run (they're free); the chart and
deck need `--charts` / `--deck`, which the bare invocation passes for you.

### The deck

1. **Stake table** — every metric per stake, rake and rakeback broken out, exclusions marked
2. **Waterfall, bb/100** — before rake → rake → rakeback → banked, shared y axis
3. **Waterfall, money** — the same decomposition in cash, where it reads the opposite way
4. **Frontier** — every mix, the undominated edge, the chosen point
5. **Frontier, in downswings** — the same choice on the peak-to-trough axis
6. **Configurations** — the optimum with two safer and two bolder frontier neighbours
7. **Step up** — the cheapest way into each higher stake, and what it costs
8. **Simulation** — a million hands, twenty thousand times: drawdowns and outcomes
9. **Methodology** — what was assumed, and what that does to the numbers

### Two kinds of downswing

Easy to conflate, and only one has a closed form.

**Loss below your starting bankroll** is what ruin measures. Start on €10k, run to
€15k, fall to €5k: that's a €5k loss below start. Over unlimited time it's bounded
and exactly exponential, so its quantiles are free — and its 99th percentile *is*
your bankroll at a 1% tolerance. Your risk tolerance is a downswing quantile.

**Peak-to-trough drawdown** is what a downswing feels like — the same episode is a
€10k fall. It has **no all-time value**: given unlimited time it grows without
bound, because a winning bankroll keeps making new highs to fall from. Every
peak-to-trough figure is therefore "within N hands" and nothing else.

That asymmetry is the whole reason `sim.py` exists. The frontier table's `typical`
and `1-in-10` columns are the first kind; the deck's simulation slide is the
second.

`mode = "downswing"` prices the **second** kind — the one you feel, not the one
that busts you. That is deliberate: losing €7k off a €15k high is what makes a
player move down, even though it is only a €2k loss below start.

One consequence worth knowing. `sim.simulate` walks in 200,000-hand chunks and
only freezes a busted path from the *next* chunk, so over a horizon shorter than
that there is no absorption at all and the worst peak-to-trough fall is the
unconstrained one — a path can "fall" further than it had money to lose. That
overstates the downswing rather than understating it, which is the same direction
as every other assumption here, but it does mean a `downswing_hands` under 200k is
measuring a slightly idealised path. `tests/test_currency_and_risk_mode.py` pins
the behaviour so it is not mistaken for a bug.

### The simulation

`sim_hands` × `sim_paths` in `config.toml` (default 1,000,000 hands × 20,000
lifetimes, ~8 seconds). Static mix, fixed stakes, no move-down rule, ruin
absorbing — so it's an upper bound on risk, not a forecast.

Its test oracle is the closed form: over a long horizon the loss-below-start
distribution must reproduce `ruin.loss_below_start_quantile`. A simulation that
disagrees where the maths is known has a bug, and `tests/test_sim.py` asserts both
that convergence *and* that peak-to-trough keeps growing while loss-below-start
doesn't.

Every figure is recomputed at build time from the same functions the terminal
uses, so a slide cannot disagree with the CLI. Nothing is hardcoded.

`shotopt/pptx_common.py` is **copied** from the nemesis-mvp analytics repo rather
than imported, so this repo depends on nothing over there — with the usual cost
of a copy, that fixes don't flow between them. The branded template lives at
`assets/deck_template.pptx` and is gitignored; without it the deck still builds,
just with plain styling.

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
  money.py           the display currency: EUR in, your currency out, nothing between
  tolerance.py       the risk rules (ruin / downswing / both), behind one interface
  mix.py             the answer: screen the stakes, enumerate and score every mix
  ruin.py            risk of ruin, drawdown, effective sigma
  kelly.py           sizing and growth (used by report/stake only)
  estimation.py      standard errors, intervals, shaded win rates
  rates.py           bb/100 -> money per hour
  analysis.py        the only module that knows about both config and maths
  charts.py          the two frontier charts
  export.py          CSV copies of the two printed tables
  workbook.py        the deck's numbers as an xlsx, built in the same pass
  sim.py             Monte Carlo over a fixed hand horizon
  deck.py            the PPTX
  pptx_common.py     deck infrastructure, copied from nemesis-mvp (a fork, not a mirror)
  cli.py             the command line
tests/               201 tests, no dependencies (pytest or stdlib unittest)
docs/theory.md       derivations and where they come from
```
