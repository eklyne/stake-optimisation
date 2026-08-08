"""Command line interface.

    py -m shotopt report
    py -m shotopt stake 200NL
    py -m shotopt kelly

`--bankroll`, `--tables` and `--ruin-tolerance` override the config file on any
command, so the inputs can be swept without editing anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import estimation, kelly, mix
from .analysis import StakeReport, best_affordable, build_reports
from .config import Config, ConfigError, load_config

__all__ = ["main"]


def _eur(value: float) -> str:
    return f"{value:,.0f}"


def _blank(value: object) -> str:
    return "-" if value is None else str(value)


def _rule(width: int) -> str:
    return "-" * width


def _print_header(config: Config) -> None:
    print()
    print(
        f"Bankroll EUR {_eur(config.bankroll_eur)}   "
        f"{config.tables} tables   "
        f"ruin tolerance {config.ruin_tolerance:.2%}   "
        f"Kelly k={config.kelly_fraction:g}"
    )
    notes = []
    if config.winrate_haircut_bb_per_table:
        notes.append(
            f"win rate haircut {config.winrate_haircut_bb_per_table:g} bb/100 per extra table"
        )
    if config.table_correlation:
        notes.append(f"table correlation {config.table_correlation:g}")
    if notes:
        print("Assumptions in play: " + "; ".join(notes))


def cmd_report(config: Config, reports: list[StakeReport]) -> None:
    _print_header(config)
    print()

    columns = (
        ("stake", 9, "<"),
        ("EUR/hr", 9, ">"),
        ("buy-ins", 8, ">"),
        ("ruin", 9, ">"),
        ("", 4, "<"),
        ("roll for tol.", 14, ">"),
        ("Kelly roll", 12, ">"),
        ("P(-50%)", 9, ">"),
    )
    header = "  ".join(f"{name:{align}{width}}" for name, width, align in columns)
    print(header)
    print(_rule(len(header)))

    for report in reports:
        verdict = "OK" if report.within_tolerance else "NO"
        need = (
            _eur(report.bankroll_for_tolerance_eur)
            if report.bankroll_for_tolerance_eur is not None
            else "-"
        )
        need_buyins = (
            f" ({report.buyins_for_tolerance:.0f}bi)"
            if report.buyins_for_tolerance is not None
            else ""
        )
        kelly_roll = (
            _eur(report.kelly_bankroll_eur) if report.kelly_bankroll_eur is not None else "-"
        )
        print(
            "  ".join(
                [
                    f"{report.stake.name:<9}",
                    f"{report.eur_per_hour:>9,.0f}",
                    f"{report.buyins:>8.0f}",
                    f"{report.risk_of_ruin:>9.2%}",
                    f"{verdict:<4}",
                    f"{need + need_buyins:>14}",
                    f"{kelly_roll:>12}",
                    f"{report.drawdown_50:>9.1%}",
                ]
            )
        )

    print()
    best = best_affordable(reports)
    if best is None:
        print(
            "VERDICT: nothing listed clears your ruin tolerance at this bankroll.\n"
            "         Play below the smallest stake here, or accept more risk."
        )
    else:
        print(
            f"VERDICT: {best.stake.name} - the highest EUR/hour that stays inside "
            f"{config.ruin_tolerance:.2%} ruin\n"
            f"         ({best.eur_per_hour:,.0f} EUR/hr, ruin {best.risk_of_ruin:.2%}, "
            f"P(-50%) {best.drawdown_50:.1%})."
        )
        blocked = [r for r in reports if not r.within_tolerance and r.stake.bb_eur > best.stake.bb_eur]
        if blocked:
            nxt = min(blocked, key=lambda r: r.stake.bb_eur)
            if nxt.bankroll_for_tolerance_eur is not None:
                shortfall = nxt.bankroll_for_tolerance_eur - config.bankroll_eur
                print(
                    f"         {nxt.stake.name} needs EUR {_eur(nxt.bankroll_for_tolerance_eur)} "
                    f"- another EUR {_eur(shortfall)}."
                )
    print()
    print(
        "Ruin and P(-50%) assume you keep playing that stake at a fixed size forever.\n"
        "They are an upper bound on the real risk: in practice you would move down."
    )
    print()


def cmd_stake(config: Config, reports: list[StakeReport], name: str) -> int:
    matches = [r for r in reports if r.stake.name.lower() == name.lower()]
    if not matches:
        available = ", ".join(r.stake.name for r in reports)
        print(f"No stake named '{name}'. Configured stakes: {available}", file=sys.stderr)
        return 2
    report = matches[0]
    stake = report.stake

    _print_header(config)
    print()
    print(f"{stake.name}  (bb = EUR {stake.bb_eur:g}, buy-in = EUR {_eur(stake.buyin_eur)})")
    print(_rule(60))
    print(f"  win rate            {stake.winrate_bb100:>10.2f} bb/100")
    if report.winrate_eff != stake.winrate_bb100:
        print(f"  after table haircut {report.winrate_eff:>10.2f} bb/100")
    print(f"  std dev             {stake.stdev_bb100:>10.2f} bb/100")
    if report.stdev_eff != stake.stdev_bb100:
        print(f"  after correlation   {report.stdev_eff:>10.2f} bb/100")
    print(f"  hourly              {report.eur_per_hour:>10,.0f} EUR/hr")
    print()
    print(f"  your roll           {report.buyins:>10.1f} buy-ins ({report.bankroll_bb:,.0f} bb)")
    print(f"  risk of ruin        {report.risk_of_ruin:>10.2%}   "
          f"({'inside' if report.within_tolerance else 'OUTSIDE'} tolerance)")
    print(f"  P(lose half)        {report.drawdown_50:>10.1%}")
    if report.bankroll_for_tolerance_eur is not None:
        print(f"  roll for tolerance  {report.bankroll_for_tolerance_eur:>10,.0f} EUR "
              f"({report.buyins_for_tolerance:.0f} buy-ins)")
    if report.kelly_bankroll_eur is not None:
        print(f"  Kelly roll (k={config.kelly_fraction:g})   {report.kelly_bankroll_eur:>10,.0f} EUR "
              f"({report.kelly_buyins:.0f} buy-ins)")
    if report.supported_bb_eur is not None:
        print(f"  roll supports bb of {report.supported_bb_eur:>10.2f} EUR  "
              f"(round DOWN to a real stake)")

    print()
    if stake.hands is None:
        print("  No `hands` in the config for this stake, so there is no confidence")
        print("  interval to show - the win rate above is being treated as known,")
        print("  which it is not.")
    else:
        low, high = report.winrate_ci
        stderr = estimation.winrate_stderr(report.stdev_eff, stake.hands)
        print(f"  measured over       {stake.hands:>10,} hands")
        print(f"  standard error      {stderr:>10.2f} bb/100")
        print(f"  95% interval        {low:>10.2f} to {high:.2f} bb/100")
        print(f"  shaded (-1 SE)      {report.shaded_winrate:>10.2f} bb/100")
        if report.shaded_kelly_bankroll_eur is not None:
            print(f"  roll on shaded rate {report.shaded_kelly_bankroll_eur:>10,.0f} EUR "
                  f"- size off this, not the point estimate")
        else:
            print("  shaded rate is not positive - this sample cannot justify the stake")
        for precision in (2.0, 1.0):
            needed = estimation.hands_for_precision(report.stdev_eff, precision)
            print(f"  +/-{precision:g} bb/100 needs   {needed:>10,.0f} hands"
                  f"  ({needed / max(stake.hands, 1):.1f}x what you have)")
    print()
    return 0


def cmd_mix(config: Config) -> int:
    """The main event: which distribution of tables across stakes is best."""
    _print_header(config)
    print()

    try:
        allocations = mix.all_allocations(config)
    except mix.AllocationLimit as exc:
        print(f"cannot enumerate allocations: {exc}", file=sys.stderr)
        return 2

    inside = [a for a in allocations if a.within_tolerance]
    print(
        f"{len(allocations):,} ways to split {config.tables} tables across "
        f"{len(config.stakes)} stakes; {len(inside):,} stay inside "
        f"{config.ruin_tolerance:.2%} ruin."
    )
    print()

    best = mix.best_allocation(allocations)
    if best is None:
        cheapest = min(allocations, key=lambda a: a.risk_of_ruin)
        print("No allocation clears your tolerance at this bankroll.")
        print(f"The safest available is {cheapest.label}, at {cheapest.risk_of_ruin:.2%}.")
        return 0

    single = max(
        (a for a in allocations if sum(1 for c in a.counts if c) == 1 and a.within_tolerance),
        key=lambda a: a.eur_per_hour,
        default=None,
    )

    print("BEST MIX")
    print(f"  {best.label}")
    print(f"  {best.eur_per_hour:,.0f} EUR/hr   ruin {best.risk_of_ruin:.2%}   "
          f"P(-50%) {best.drawdown_50:.1%}")
    if single is not None and single.counts != best.counts:
        uplift = best.eur_per_hour - single.eur_per_hour
        print(
            f"  Against the best single-stake option ({single.label}, "
            f"{single.eur_per_hour:,.0f} EUR/hr): +{uplift:,.0f} EUR/hr, "
            f"+{uplift / max(single.eur_per_hour, 1e-9):.0%}."
        )
    print()

    step = mix.marginal_step_up(best, config)
    if step is not None:
        stepped, gained, added = step
        verdict = "inside tolerance" if stepped.within_tolerance else "OUTSIDE tolerance"
        print("ONE MORE TABLE UP")
        print(f"  {stepped.label}")
        print(f"  buys {gained:+,.0f} EUR/hr, costs {added:+.2%} ruin -> {verdict}")
        print()

    print("EFFICIENT FRONTIER  (the only mixes worth considering, at any tolerance)")
    print()
    header = f"  {'EUR/hr':>8}  {'ruin':>9}  {'P(-50%)':>8}  mix"
    print(header)
    print(_rule(len(header) + 24))
    for allocation in mix.frontier(allocations):
        marker = " <- best inside tolerance" if allocation.counts == best.counts else ""
        print(
            f"  {allocation.eur_per_hour:>8,.0f}  {allocation.risk_of_ruin:>9.2%}  "
            f"{allocation.drawdown_50:>8.1%}  {allocation.label}{marker}"
        )
    print()
    print(
        "A static snapshot at this bankroll, assuming tables deal independently\n"
        "and you can actually get the seats (set `max_tables` per stake if not).\n"
        "The dynamic version - move up through one threshold, down through\n"
        "another - is the simulation, and is not built yet."
    )
    print()
    return 0


def cmd_kelly(config: Config) -> None:
    _print_header(config)
    print()
    print("  k     growth (share of full)   variance (share)   P(ever -50%)")
    print(_rule(62))
    for k in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
        growth = k * (2.0 - k)
        variance = kelly.fractional_variance_ratio(k)
        if k < 2.0:
            drawdown = f"{kelly.rescaled_drawdown_probability(0.5, k):>12.1%}"
        else:
            drawdown = f"{'certain':>12}"
        marker = "  <- your setting" if abs(k - config.kelly_fraction) < 1e-9 else ""
        print(f"  {k:<4g}  {growth:>20.0%}   {variance:>16.0%}   {drawdown}{marker}")
    print()
    print("  Half Kelly keeps three quarters of the growth for a quarter of the")
    print("  variance. Betting at twice the optimal fraction earns nothing at all.")
    print("  Since your win rate is an estimate, shade down - the penalty for")
    print("  underbetting is mild and the penalty for overbetting is not.")
    print()


def _build_parser() -> argparse.ArgumentParser:
    # The shared flags are attached to the top-level parser AND to every
    # subparser, so `shotopt --charts report` and `shotopt report --charts` both
    # work. Defaults are SUPPRESS rather than None: without that, a subparser's
    # own default would overwrite a value already parsed at the top level.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help="path to config.toml"
    )
    common.add_argument(
        "--bankroll", type=float, default=argparse.SUPPRESS, help="override bankroll, EUR"
    )
    common.add_argument(
        "--tables", type=int, default=argparse.SUPPRESS, help="override table count"
    )
    common.add_argument(
        "--ruin-tolerance",
        type=float,
        default=argparse.SUPPRESS,
        help="override ruin tolerance, e.g. 0.05",
    )
    common.add_argument(
        "--kelly-fraction",
        type=float,
        default=argparse.SUPPRESS,
        help="override Kelly fraction",
    )
    common.add_argument(
        "--charts",
        nargs="?",
        const="output",
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="also write the PNG charts (default directory: output/)",
    )

    parser = argparse.ArgumentParser(
        prog="shotopt",
        description="Analytic bankroll and stake-selection calculator.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "mix", help="best distribution of tables across stakes (default)", parents=[common]
    )
    subparsers.add_parser("report", help="one row per stake", parents=[common])
    stake_parser = subparsers.add_parser(
        "stake", help="detail on a single stake", parents=[common]
    )
    stake_parser.add_argument("name")
    subparsers.add_parser("kelly", help="the fractional-Kelly trade-off table", parents=[common])
    return parser


DEFAULT_ARGV = ["mix", "--charts"]
"""What a bare `run.bat` does: the full job, text and charts.

Running the tool with no arguments should refresh everything, not silently skip
the charts and leave stale PNGs on disk. Any explicit subcommand opts out again -
`run.bat mix` prints without rendering.
"""


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = _build_parser().parse_args(argv or DEFAULT_ARGV)
    get = lambda name: getattr(args, name, None)  # noqa: E731 - SUPPRESS leaves gaps

    try:
        config = load_config(get("config"))
        config = config.replace(
            bankroll_eur=get("bankroll"),
            tables=get("tables"),
            ruin_tolerance=get("ruin_tolerance"),
            kelly_fraction=get("kelly_fraction"),
        )
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    reports = build_reports(config)
    command = args.command or "mix"

    exit_code = 0
    if command == "mix":
        exit_code = cmd_mix(config)
    elif command == "report":
        cmd_report(config, reports)
    elif command == "stake":
        exit_code = cmd_stake(config, reports, args.name)
    elif command == "kelly":
        cmd_kelly(config)

    charts_dir = get("charts")
    if charts_dir is not None:
        from . import charts  # imported lazily so the text commands need no matplotlib

        written = charts.write_all(reports, config, Path(charts_dir))
        print(f"Charts written to {Path(charts_dir).resolve()}:")
        for path in written:
            print(f"  {path.name}")
        print()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
