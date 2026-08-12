"""What currency the answers are READ in, which is not the one they are computed in.

The tables are EUR. Every stake's big blind, every win rate translated into money,
every simulated bankroll path - all of it is euros, because that is what actually
moves. But the person reading the output banks in sterling, and "EUR 41/hour" is a
number they have to convert in their head before it means anything.

So this module draws one line: **the model is EUR end to end, and the currency is a
display skin over it**. `Config.bankroll_eur`, `Allocation.mean_eur_per_100`,
`Allocation.eur_per_hour` and everything downstream keep their names and their
units. Conversion happens in exactly two places:

* **in**, when the config is loaded - the money you TYPE (bankroll, downswing
  threshold) is in your currency, so it is converted to euros once, at the door;
* **out**, at every print/label/cell site, via `fmt` and `axis`.

Nothing in between knows the currency exists. That is deliberate: a half-converted
pipeline, where some intermediate is sterling and some is euros, is the kind of bug
that produces a plausible answer that is wrong by 16%.

The rate is a FIXED CONSTANT from the config, not a live quote. It has to be: a
bankroll plan that moves with the spot rate is not a plan, and re-running the deck
should not silently change every figure on it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Currency", "EUR", "BASE_CODE"]

BASE_CODE = "EUR"
"""The currency the model computes in - the one the tables are actually dealt in."""


@dataclass(frozen=True)
class Currency:
    """A display currency, and the fixed rate that reaches it from euros."""

    code: str
    eur_per_unit: float
    """Euros to one unit of this currency. 1.16 means 1 GBP = 1.16 EUR."""

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("currency code must not be empty")
        if self.eur_per_unit <= 0:
            raise ValueError(f"eur_per_unit must be positive, got {self.eur_per_unit}")

    @property
    def is_base(self) -> bool:
        """True when no conversion happens at all - the identity case."""
        return self.code == BASE_CODE and self.eur_per_unit == 1.0

    def to_eur(self, amount: float) -> float:
        """A figure the user typed, in euros. Used ONLY at config load."""
        return amount * self.eur_per_unit

    def from_eur(self, eur: float) -> float:
        """An internal euro figure, in the display currency. Used ONLY to print."""
        return eur / self.eur_per_unit

    def fmt(self, eur: float, dp: int = 0) -> str:
        """A euro amount as a labelled string: `GBP 8,621`.

        Takes EUROS, like every other function here - callers pass the internal
        value and never pre-convert, so there is no way to double-convert.
        """
        return f"{self.code} {self.from_eur(eur):,.{dp}f}"

    def plain(self, eur: float, dp: int = 0) -> str:
        """As `fmt`, without the code - for tables that carry the unit in a header."""
        return f"{self.from_eur(eur):,.{dp}f}"

    def axis(self, suffix: str = "") -> str:
        """An axis label: `GBP`, `GBP / hour`, `GBP / 100 hands`."""
        return f"{self.code} {suffix}".strip()

    def note(self) -> str | None:
        """The one-line disclosure of the rate, or None when nothing was converted.

        Any figure a reader might reconcile against their tracker has been moved,
        so the rate used has to be stated wherever those figures appear.
        """
        if self.is_base:
            return None
        return (
            f"Money is shown in {self.code}, converted from the {BASE_CODE} the tables "
            f"are dealt in at a fixed {self.eur_per_unit:g} {BASE_CODE} = 1 {self.code}. "
            f"bb/100 figures are unaffected."
        )


EUR = Currency(BASE_CODE, 1.0)
"""The identity currency - what you get when the config says nothing."""
