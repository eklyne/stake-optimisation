# Theory

Where the formulas come from, why they take the shape they do, and what they
assume. Nothing here is original — Kelly (1956) and the diffusion approximation to
a gambler's-ruin problem are both long-settled. It is written down so the code can
be built on the established result rather than reinventing it, and so the eventual
simulation has something to check itself against.

## The framing

Choosing a stake has two covariates and one rule:

> Take the highest-EV configuration available that stays inside your risk
> tolerance.

The force of this is *deflationary*. Table availability at the higher stake, win
rate degradation from more tables, your own attention and tilt at bigger stakes —
all real, all genuinely affecting the decision, none of them a third covariate.
They are terms inside the EV estimate. Readiness and ego are not even that.

Two amendments keep it honest, and both are implemented rather than noted:

1. **Ruin is not a cliff, and variance costs you short of it.** Because the roll is
   re-invested, a drawdown that does not bust you still forces a move down, which
   lowers your *future* EV — so variance belongs in the objective, not only in the
   constraint. Strictly, the thing to maximise is long-run growth rate, not
   per-hand EV; the two coincide only when the bankroll is large relative to the
   stake. This is why the tool reports drawdown probabilities alongside ruin, and
   why the Kelly objective (below) is a log one.
2. **EV is estimated, not known.** "The highest-EV configuration" is really the
   highest *point estimate*, and the stake the rule pushes you toward is the one
   you have played least. The response is not to stop modelling — uncertainty is
   the working condition, the same one you accept every time you put money in the
   pot without seeing the other guy's cards. The response is to model it: see
   `estimation.py`, and shade the sizing (`shaded_winrate`) rather than pretending
   the point estimate is a fact.

## Kelly

Given a repeated favourable bet and a bankroll you re-invest, Kelly asks what
fraction to put at risk each time, and answers: the fraction maximising the
expected **logarithm** of the bankroll — equivalently the long-run exponential
growth rate — not the fraction maximising expected profit.

Maximising per-bet EV alone says bet everything every time, which busts you with
probability approaching 1. The log objective encodes compounding: a 50% loss needs
a 100% gain to undo it, so losses hurt the growth rate more than equal gains help.
That is amendment 1 in formal dress.

For a discrete bet at odds *b* with win probability *p*, the classic result is
*f\* = (bp − q)/b* — edge over odds. For a continuous, roughly-Gaussian outcome
stream, which is what a poker win rate is:

    f* = μ / σ²

Edge over variance. Exposure scales with edge and falls with the **square** of
variance, which is why a modest win rate at high variance justifies far less
exposure than intuition suggests.

### Translating to poker

The translation is where this usually goes wrong. Poker offers no "what fraction of
my roll do I bet" dial. The divisible variable is the **stake**. Playing 100NL on a
€5,000 roll *is* an exposure choice in Kelly's sense.

Let the big blind be worth `v` euros and the bankroll be `B_eur`. Per 100 hands the
euro outcome has mean `μv` and variance `σ²v²`. Maximising the log-growth of
`B_eur` over `v` gives:

    v* = B_eur · μ / σ²

and reading it the other way, the full-Kelly bankroll for a given stake, in big
blinds:

    B* = σ² / μ

Worth having the magnitude to hand: μ=5, σ=90 gives 1620bb — **16 buy-ins at full
Kelly, 32 at half**. The conventional 20/30/50-buy-in rules land in the same
neighbourhood, which is the point: they are a serviceable proxy for this
calculation, not independent wisdom. `tests/test_maths.py` pins that
correspondence, on the reasoning that if it ever breaks, the maths broke — not the
folklore.

### Fractional Kelly

Full Kelly is brutal in practice. Under it, the probability of the roll ever
dropping to fraction *x* of its starting value is *x* itself — so a 50% drawdown is
a coin flip. At fraction *k* of full Kelly:

| | |
|---|---|
| growth | `k(2-k)` × full |
| variance | `k²` × full |
| P(ever reaching fraction x) | `x^(2/k - 1)` |

Half Kelly therefore keeps **three quarters of the growth for a quarter of the
variance**, and turns that coin-flip drawdown into 12.5%. Growth is symmetric about
k=1 — k=0.6 and k=1.4 grow identically — but risk is not, and at k=2 growth is zero.
So **overbetting is much more damaging than underbetting**, and since your win rate
is always an estimate, fractional Kelly *is* the principled response to estimation
error: you shade down deliberately to buy robustness against being wrong about
yourself.

## Risk of ruin

The same diffusion model — bankroll as Brownian motion with drift μ and volatility
σ per 100 hands — gives the standard approximation for ever touching zero:

    R ≈ exp(-2μB / σ²)

This collapses both covariates into one closed-form relation between win rate,
variance, bankroll and ruin probability. Moving the absorbing barrier from zero up
to `(1-x)B` gives the probability of ever losing fraction *x* of the roll, which is
the same function evaluated at a smaller bankroll — that is
`ruin.drawdown_probability`.

### The e⁻² result

Substituting the full-Kelly bankroll `B* = σ²/μ` into the ruin formula, the
exponent becomes exactly −2 and everything else cancels:

    R(B*) = e⁻² ≈ 13.5%

**Regardless of win rate or variance.** Half Kelly gives e⁻⁴ ≈ 1.8%. These are
tested directly (`TestCrossChecks`) because they tie the two modules together and
are exactly where a sign error would hide.

### The two drawdown laws

`ruin.drawdown_probability` and `kelly.rescaled_drawdown_probability` answer
similar-sounding questions and are **not** the same function:

- the first assumes a **fixed stake** — you grind 100NL regardless of what the roll
  does;
- the second assumes **continuous rescaling** — exposure tracks the current
  bankroll, which is what Kelly actually prescribes.

Real poker is between them: you rescale, but in discrete jumps, when you change
stake. That gap is precisely what the eventual simulation exists to close.

## Where poker breaks the assumptions

Stated plainly, because the tool cannot fix them:

- **Stakes are not continuously divisible.** Kelly assumes they are; poker offers
  rungs (50/100/200NL), so the exposure you want usually falls between two of them
  and gets rounded. The fix is not a better formula — it is a **fractional mix of
  tables across stakes**, which restores the divisibility Kelly assumes and turns a
  rounding problem into an allocation you can actually set. That is the next build.
- **Hands are not independent bets.** Multi-tabling correlates outcomes within a
  session, and tilt correlates them further. Modelled, optionally and crudely, by
  `table_correlation`.
- **A poker bankroll usually has a floor** — a job, a life roll — which makes
  literal ruin less absolute than the maths assumes, and makes *drawdown* the more
  behaviourally meaningful constraint. This is the better reason to look at the
  P(-50%) column than at the ruin column.
- **Ruin here assumes an infinite horizon.** "Ever" is a long time. Over a finite
  number of hands the true probability is lower, so these figures are conservative.

## What comes next

The gap this repo does not close: shot-taking is conventionally binary — you play
50NL, then one day you "take a shot" at 100NL and your whole session moves up. But
a multi-tabler never has to switch anything. Volume is already divisible across
tables, so the real decision variable is the **share of simultaneous tables at each
stake**, and shot-taking becomes a dial rather than a step.

That is a portfolio problem, and the interesting part is that the allocation is
**dynamic**: the roll moves while you play it, so the right mix is a function of
the bankroll you have *now*. The object to search for is not a single best
allocation but a **policy** — if the roll changes by X, change the mix by Y — with
hysteresis between the move-up and move-down thresholds so paths near the boundary
do not thrash. Kelly supplies the rule for free: recompute `f* = μ/σ²` against the
current bankroll and round to the nearest achievable mix; move-down rules then fall
out of the same optimisation instead of being inherited as folklore.

Two outputs that framing gets and this one cannot:

- it **prices a partial shot**, currently an unpriceable "feel" decision;
- it makes the EV drag of variance **measurable rather than assumed** — every path
  that breaches a threshold pays the move-down cost automatically.

## Reading

- Kelly, *A New Interpretation of Information Rate* (1956).
- Thorp, *Beat the Dealer*; and *The Kelly Criterion in Blackjack, Sports Betting,
  and the Stock Market*.
- Chen & Ankenman, *The Mathematics of Poker* — risk of ruin and bankroll sizing in
  this exact language.
