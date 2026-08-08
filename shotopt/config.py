"""Loading and validating the four inputs.

The tool takes exactly four things: a bankroll in euros, how many tables are
played at once, a win rate and standard deviation for each stake there is data
on, and a risk-of-ruin tolerance. Everything else is a default that is rarely
touched.

Validation is strict and loud. A silently-accepted bad standard deviation
produces a plausible-looking bankroll recommendation that is wrong by a factor of
several, and nothing downstream would flag it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Stake", "Config", "ConfigError", "load_config", "DEFAULT_CONFIG_PATH"]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"

_STAKE_REQUIRED = ("name", "bb_eur", "winrate_bb100", "stdev_bb100")
_STAKE_KNOWN = _STAKE_REQUIRED + (
    "hands", "max_tables", "rake_bb100", "current_hands"
)
_TOP_LEVEL_KNOWN = frozenset(
    {
        "bankroll_eur",
        "tables",
        "ruin_tolerance",
        "kelly_fraction",
        "hands_per_hour_per_table",
        "winrate_haircut_bb_per_table",
        "table_correlation",
        "rakeback_pct",
        "timescale_hands",
        "sim_paths",
        "stake",
    }
)


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
    tables: int
    ruin_tolerance: float
    stakes: tuple[Stake, ...]
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

    unknown = set(raw) - _TOP_LEVEL_KNOWN
    if unknown:
        raise ConfigError(f"{path}: unknown top-level key(s) {sorted(unknown)}")

    where = str(path)
    bankroll_eur = _require_number(raw, "bankroll_eur", where)
    ruin_tolerance = _require_number(raw, "ruin_tolerance", where)

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
        raise ConfigError(f"{where}: bankroll_eur must be positive, got {bankroll_eur}")
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
        kelly_fraction=kelly_fraction,
        hands_per_hour_per_table=hands_per_hour_per_table,
        winrate_haircut_bb_per_table=haircut,
        table_correlation=correlation,
        rakeback_pct=rakeback_pct,
        timescale_hands=timescale_hands,
        sim_paths=sim_paths,
    )
