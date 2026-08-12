"""Loading and validating the four inputs.

The tool takes exactly four things: a bankroll, how many tables are played at
once, a win rate and standard deviation for each stake there is data on, and a
risk tolerance. Everything else is a default that is rarely touched.

Two of those four have a choice attached, and both are resolved here so nothing
downstream has to think about them again:

* **The risk tolerance** comes in two shapes - an all-time risk of ruin, or a
  probability of a downswing of a stated size over a stated number of hands. See
  `tolerance.py`. The `[risk]` block picks one; both sets of numbers are carried
  either way, because the deck draws both pictures regardless of which one binds.
* **The currency** money is read in. The model is euros end to end (see
  `money.py`); a display currency converts the money you TYPE on the way in, and
  the money you READ on the way out. `bankroll_eur` below is therefore always
  euros, whatever the file said.

Validation is strict and loud. A silently-accepted bad standard deviation
produces a plausible-looking bankroll recommendation that is wrong by a factor of
several, and nothing downstream would flag it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .money import EUR, Currency

__all__ = [
    "Stake", "Config", "ConfigError", "load_config", "DEFAULT_CONFIG_PATH", "RISK_MODES",
]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"

RISK_MODES = ("ruin", "downswing", "both")
"""The legal values of `[risk] mode`. Lives here, not in `tolerance`, so that
validating a config never has to import the simulation or numpy behind it.

`both` is the intersection - a mix must clear the ruin bar AND the downswing
bar - so the stricter of the two decides, and which one that is changes on its
own as the bankroll moves."""

_MODES_NEEDING_DOWNSWING = ("downswing", "both")
"""Modes where `downswing_amount` stops being optional."""

_STAKE_REQUIRED = ("name", "bb_eur", "winrate_bb100", "stdev_bb100")
_STAKE_KNOWN = _STAKE_REQUIRED + (
    "hands", "max_tables", "rake_bb100", "current_hands", "measured_winrate_bb100"
)
_TOP_LEVEL_KNOWN = frozenset(
    {
        "bankroll",
        "tables",
        "currency",
        "fx_eur_per_unit",
        "kelly_fraction",
        "hands_per_hour_per_table",
        "winrate_haircut_bb_per_table",
        "table_correlation",
        "rakeback_pct",
        "timescale_hands",
        "sim_paths",
        "risk",
        "stake",
    }
)
_RISK_KNOWN = frozenset(
    {
        "mode",
        "ruin_tolerance",
        "downswing_amount",
        "downswing_hands",
        "downswing_probability",
    }
)

_MOVED_KEYS = {
    "bankroll_eur": (
        "rename it to 'bankroll' - it is now read in the display currency set by "
        "'currency' (which defaults to EUR, so the value need not change)"
    ),
    "ruin_tolerance": "move it under the [risk] table",
}
"""Keys that used to be top-level. The whitelist would reject these anyway, but
with an unhelpful 'unknown key' - and silently dropping a risk tolerance or a
bankroll is exactly the kind of thing that must never happen quietly."""


class ConfigError(ValueError):
    """Raised when the config is missing, malformed, or internally implausible."""


@dataclass(frozen=True)
class Stake:
    """One stake there is data on."""

    name: str
    bb_eur: float
    winrate_bb100: float
    stdev_bb100: float
    hands: int | None = None
    max_tables: int | None = None
    """Seats you can realistically get at this stake at once. None = no limit.

    A real constraint on the mix, and the one most likely to bind: the optimiser
    will happily allocate eight tables to a stake that never has eight good games
    running."""
    rake_bb100: float | None = None
    """Rake paid per 100 hands, in bb - the base the rakeback percentage applies
    to. Falls sharply as stakes rise, since a currency-capped rake bites less on
    bigger bb-denominated pots, which is why rakeback is worth most at the bottom
    of the ladder."""
    measured_winrate_bb100: float | None = None
    """What the sample actually says, when `winrate_bb100` is an assumption.

    Set this wherever the modelled win rate is NOT the measurement, so the deck
    can show the two side by side instead of drawing a confidence interval
    around a number no sample supports. Leave it unset where the modelled rate
    IS the measurement - the deck then treats them as the same thing."""
    current_hands: float | None = None
    """Hands actually played at this stake in the period being reviewed.

    Only ever used as a RATIO, to reconstruct how the table time was really
    split, so the absolute figures and the period they cover don't matter as
    long as they are consistent across stakes."""

    @property
    def buyin_eur(self) -> float:
        """A 100bb buy-in, in euros - the unit bankroll conventions are stated in."""
        return 100.0 * self.bb_eur

    def bankroll_bb(self, bankroll_eur: float) -> float:
        """A euro bankroll expressed in big blinds of this stake."""
        return bankroll_eur / self.bb_eur


@dataclass(frozen=True)
class Config:
    """The four inputs, plus the defaults."""

    bankroll_eur: float
    """ALWAYS euros, whatever currency the file typed it in."""
    tables: int
    ruin_tolerance: float
    """Kept in both modes: the ruin figure is reported and charted either way."""
    stakes: tuple[Stake, ...]

    risk_mode: str = "ruin"
    """Which rule decides the answer - see `tolerance.MODES`."""
    downswing_amount_eur: float | None = None
    """X: the peak-to-trough fall being priced, in euros. Required in downswing
    mode; None in ruin mode, where the downswing chart is drawn with no line on it."""
    downswing_hands: int = 500_000
    """Y: the horizon the downswing question is asked over. Peak-to-trough
    drawdown grows without bound over unlimited time, so there is no such thing as
    an all-time value and the horizon is not optional."""
    downswing_probability: float = 0.05
    """p: how often you are willing to have a downswing that bad, or worse."""

    currency: Currency = EUR
    """Display only. Never appears in a calculation - see `money.py`."""

    kelly_fraction: float = 0.5
    hands_per_hour_per_table: float = 75.0
    winrate_haircut_bb_per_table: float = 0.0
    table_correlation: float = 0.0
    rakeback_pct: float = 0.0
    """Share of rake rebated. Applies to every stake's `rake_bb100`."""
    timescale_hands: int = 1_000_000
    """The period every simulated figure covers, in hands.

    ONE horizon for the whole tool, because peak-to-trough drawdown has no
    all-time value - given unlimited time it grows without bound - so every
    downswing number must name the stretch of play it refers to, and two
    different stretches on two different slides would be unreadable. Set it to
    a period you can picture: a year of your own volume."""
    sim_paths: int = 20_000
    """Independent lifetimes simulated."""

    def __post_init__(self) -> None:
        # Runs on CLI overrides too, so `--bankroll -500` is caught here rather
        # than surfacing as a confusing division downstream.
        if self.bankroll_eur <= 0:
            raise ConfigError(f"bankroll must be positive, got {self.bankroll_eur}")
        if self.tables < 1:
            raise ConfigError(f"tables must be at least 1, got {self.tables}")
        if not 0.0 < self.ruin_tolerance < 1.0:
            raise ConfigError(
                f"ruin_tolerance must be strictly between 0 and 1, got {self.ruin_tolerance}"
            )
        if not 0.0 < self.kelly_fraction <= 1.0:
            raise ConfigError(f"kelly_fraction must be in (0, 1], got {self.kelly_fraction}")
        if not 0.0 <= self.rakeback_pct <= 1.0:
            raise ConfigError(
                f"rakeback_pct must be a share between 0 and 1 (0.3 for 30%), "
                f"got {self.rakeback_pct}"
            )
        if self.risk_mode not in RISK_MODES:
            raise ConfigError(
                f"risk mode must be one of {list(RISK_MODES)}, got {self.risk_mode!r}"
            )
        if self.risk_mode in _MODES_NEEDING_DOWNSWING and self.downswing_amount_eur is None:
            raise ConfigError(
                f"risk mode '{self.risk_mode}' needs [risk] downswing_amount - the size "
                f"of the fall you are pricing"
            )
        if self.downswing_amount_eur is not None and self.downswing_amount_eur <= 0:
            raise ConfigError(
                f"downswing_amount must be positive, got {self.downswing_amount_eur}"
            )
        if self.downswing_hands < 100:
            raise ConfigError(
                f"downswing_hands must be at least 100, got {self.downswing_hands}"
            )
        if not 0.0 < self.downswing_probability < 1.0:
            raise ConfigError(
                f"downswing_probability must be strictly between 0 and 1, "
                f"got {self.downswing_probability}"
            )
        if not self.stakes:
            raise ConfigError("no stakes configured - nothing to report on")

    def replace(self, **changes: object) -> "Config":
        """A copy with fields overridden - used by the CLI's --bankroll etc."""
        from dataclasses import replace as _replace

        return _replace(self, **{k: v for k, v in changes.items() if v is not None})


def _require_number(raw: dict, key: str, where: str) -> float:
    if key not in raw:
        raise ConfigError(f"{where}: missing required key '{key}'")
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where}: '{key}' must be a number, got {value!r}")
    return float(value)


def _parse_currency(raw: dict, where: str) -> Currency:
    """The display currency, and the fixed rate that reaches it from euros.

    Defaults to EUR at a rate of 1.0, which makes every conversion an identity -
    so a config that says nothing about currency behaves exactly as it did before
    this existed.
    """
    code = str(raw.get("currency", EUR.code)).upper()
    if code == EUR.code:
        # A rate on the base currency can only be a mistake, and silently
        # ignoring it would leave every figure 16% out with no warning.
        rate = raw.get("fx_eur_per_unit")
        if rate is not None and float(rate) != 1.0:
            raise ConfigError(
                f"{where}: currency is EUR, so fx_eur_per_unit must be 1.0 (or absent), "
                f"got {rate}"
            )
        return EUR
    if "fx_eur_per_unit" not in raw:
        raise ConfigError(
            f"{where}: currency = '{code}' needs fx_eur_per_unit - the euros in one "
            f"{code} (e.g. 1.16 for GBP). The rate is fixed by you, not fetched."
        )
    rate = _require_number(raw, "fx_eur_per_unit", where)
    if rate <= 0:
        raise ConfigError(f"{where}: fx_eur_per_unit must be positive, got {rate}")
    return Currency(code, rate)


def _parse_risk(raw: dict, currency: Currency, where: str) -> dict:
    """The `[risk]` block: which rule binds, and the numbers behind both of them.

    Both rules' settings are read whatever the mode, because the deck draws both
    frontier charts either way - only `mode` decides which one gates the answer.
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: [risk] must be a table, got {raw!r}")
    unknown = set(raw) - _RISK_KNOWN
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) in [risk]: {sorted(unknown)}")

    mode = str(raw.get("mode", "ruin"))
    if mode not in RISK_MODES:
        raise ConfigError(
            f"{where}: [risk] mode must be one of {list(RISK_MODES)}, got {mode!r}"
        )

    if "ruin_tolerance" not in raw:
        raise ConfigError(
            f"{where}: [risk] needs ruin_tolerance even in '{mode}' mode - the ruin "
            f"figure is reported and charted whichever rule binds"
        )
    ruin_tolerance = _require_number(raw, "ruin_tolerance", f"{where} [risk]")

    amount = raw.get("downswing_amount")
    if amount is not None:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ConfigError(
                f"{where}: [risk] downswing_amount must be a number, got {amount!r}"
            )
        # Typed in the display currency, like the bankroll it is compared against.
        amount = currency.to_eur(float(amount))
    elif mode in _MODES_NEEDING_DOWNSWING:
        raise ConfigError(
            f"{where}: [risk] mode = '{mode}' needs downswing_amount - the size of "
            f"the peak-to-trough fall you are pricing, in {currency.code}"
        )

    hands = raw.get("downswing_hands", 500_000)
    if isinstance(hands, bool) or not isinstance(hands, int):
        raise ConfigError(
            f"{where}: [risk] downswing_hands must be an integer, got {hands!r}"
        )
    probability = float(raw.get("downswing_probability", 0.05))

    return {
        "mode": mode,
        "ruin_tolerance": ruin_tolerance,
        "downswing_amount_eur": amount,
        "downswing_hands": hands,
        "downswing_probability": probability,
    }


def _parse_stake(raw: dict, index: int) -> Stake:
    where = f"[[stake]] #{index + 1}"
    if "name" not in raw:
        raise ConfigError(f"{where}: missing required key 'name'")
    name = str(raw["name"])
    where = f"stake '{name}'"

    unknown = set(raw) - set(_STAKE_KNOWN)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")

    bb_eur = _require_number(raw, "bb_eur", where)
    winrate = _require_number(raw, "winrate_bb100", where)
    stdev = _require_number(raw, "stdev_bb100", where)

    if bb_eur <= 0:
        raise ConfigError(f"{where}: bb_eur must be positive, got {bb_eur}")
    if stdev <= 0:
        raise ConfigError(f"{where}: stdev_bb100 must be positive, got {stdev}")

    hands = raw.get("hands")
    if hands is not None:
        if isinstance(hands, bool) or not isinstance(hands, int) or hands <= 0:
            raise ConfigError(f"{where}: hands must be a positive integer, got {hands!r}")

    max_tables = raw.get("max_tables")
    if max_tables is not None:
        if isinstance(max_tables, bool) or not isinstance(max_tables, int) or max_tables < 0:
            raise ConfigError(
                f"{where}: max_tables must be a non-negative integer, got {max_tables!r}"
            )

    rake = raw.get("rake_bb100")
    if rake is not None:
        if isinstance(rake, bool) or not isinstance(rake, (int, float)) or rake < 0:
            raise ConfigError(
                f"{where}: rake_bb100 must be a non-negative number, got {rake!r}"
            )
        rake = float(rake)

    measured = raw.get("measured_winrate_bb100")
    if measured is not None:
        if isinstance(measured, bool) or not isinstance(measured, (int, float)):
            raise ConfigError(
                f"{where}: measured_winrate_bb100 must be a number, got {measured!r}"
            )
        measured = float(measured)
        if hands is None:
            raise ConfigError(
                f"{where}: measured_winrate_bb100 needs 'hands' - a measurement with no "
                f"sample behind it cannot be given an interval"
            )

    current = raw.get("current_hands")
    if current is not None:
        if isinstance(current, bool) or not isinstance(current, (int, float)) or current < 0:
            raise ConfigError(
                f"{where}: current_hands must be a non-negative number, got {current!r}"
            )
        current = float(current)

    return Stake(
        name=name,
        bb_eur=bb_eur,
        winrate_bb100=winrate,
        stdev_bb100=stdev,
        hands=hands,
        max_tables=max_tables,
        rake_bb100=rake,
        current_hands=current,
        measured_winrate_bb100=measured,
    )


def load_config(path: str | Path | None = None) -> Config:
    """Read and validate a config.toml."""
    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    with path.open("rb") as handle:
        try:
            raw = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: could not parse TOML - {exc}") from exc

    where = str(path)
    for moved, advice in _MOVED_KEYS.items():
        if moved in raw:
            raise ConfigError(f"{where}: '{moved}' has moved - {advice}")

    unknown = set(raw) - _TOP_LEVEL_KNOWN
    if unknown:
        raise ConfigError(f"{path}: unknown top-level key(s) {sorted(unknown)}")

    currency = _parse_currency(raw, where)
    # The one conversion on the way in. Everything below this line is euros.
    bankroll_eur = currency.to_eur(_require_number(raw, "bankroll", where))
    risk = _parse_risk(raw.get("risk", {}), currency, where)
    ruin_tolerance = risk["ruin_tolerance"]

    tables = raw.get("tables")
    if isinstance(tables, bool) or not isinstance(tables, int):
        raise ConfigError(f"{where}: 'tables' must be an integer, got {tables!r}")

    kelly_fraction = float(raw.get("kelly_fraction", 0.5))
    hands_per_hour_per_table = float(raw.get("hands_per_hour_per_table", 75.0))
    haircut = float(raw.get("winrate_haircut_bb_per_table", 0.0))
    correlation = float(raw.get("table_correlation", 0.0))
    rakeback_pct = float(raw.get("rakeback_pct", 0.0))
    timescale_hands = int(raw.get("timescale_hands", 1_000_000))
    sim_paths = int(raw.get("sim_paths", 20_000))
    if timescale_hands < 100:
        raise ConfigError(
            f"{where}: timescale_hands must be at least 100, got {timescale_hands}"
        )
    if sim_paths < 1:
        raise ConfigError(f"{where}: sim_paths must be at least 1, got {sim_paths}")

    if bankroll_eur <= 0:
        raise ConfigError(f"{where}: bankroll must be positive, got {bankroll_eur}")
    if tables < 1:
        raise ConfigError(f"{where}: tables must be at least 1, got {tables}")
    if not 0.0 < ruin_tolerance < 1.0:
        raise ConfigError(
            f"{where}: ruin_tolerance must be a probability strictly between 0 and 1, "
            f"got {ruin_tolerance}"
        )
    if not 0.0 < kelly_fraction <= 1.0:
        raise ConfigError(f"{where}: kelly_fraction must be in (0, 1], got {kelly_fraction}")
    if hands_per_hour_per_table <= 0:
        raise ConfigError(
            f"{where}: hands_per_hour_per_table must be positive, "
            f"got {hands_per_hour_per_table}"
        )
    if haircut < 0:
        raise ConfigError(
            f"{where}: winrate_haircut_bb_per_table must be non-negative, got {haircut}"
        )
    if not 0.0 <= correlation <= 1.0:
        raise ConfigError(f"{where}: table_correlation must be in [0, 1], got {correlation}")

    raw_stakes = raw.get("stake", [])
    if not raw_stakes:
        raise ConfigError(f"{where}: no [[stake]] entries - nothing to report on")
    stakes = tuple(_parse_stake(entry, i) for i, entry in enumerate(raw_stakes))

    names = [s.name for s in stakes]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ConfigError(f"{where}: duplicate stake name(s) {sorted(duplicates)}")

    return Config(
        bankroll_eur=bankroll_eur,
        tables=tables,
        ruin_tolerance=ruin_tolerance,
        stakes=stakes,
        risk_mode=risk["mode"],
        downswing_amount_eur=risk["downswing_amount_eur"],
        downswing_hands=risk["downswing_hands"],
        downswing_probability=risk["downswing_probability"],
        currency=currency,
        kelly_fraction=kelly_fraction,
        hands_per_hour_per_table=hands_per_hour_per_table,
        winrate_haircut_bb_per_table=haircut,
        table_correlation=correlation,
        rakeback_pct=rakeback_pct,
        timescale_hands=timescale_hands,
        sim_paths=sim_paths,
    )
