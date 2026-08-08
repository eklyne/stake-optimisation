"""Command line interface.

    py -m shotopt              the answer: stake screen + efficient frontier
    py -m shotopt report       per-stake detail, if all volume went to one stake
    py -m shotopt stake 200NL  one stake, with its confidence interval

`--bankroll`, `--tables` and `--ruin-tolerance` override the config file on any
command, so the inputs can be swept without editing anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import estimation, export, mix, rates
from .analysis import StakeReport, best_affordable, build_reports
from .config import Config, ConfigError, load_config

__all__ = ["main"]

_WRITTEN: list[Path] = []
"""Everything this run produced, reported in one block at the end."""


def _eur(value: float) -> str:
    return f"{value:,.0f}"


def _blank(value: object) -> str:
    return "-" if value is None else str(value)


def _rule(width: int) -> str:
    return "-" * width


def _print_header(config: Config, kelly_fraction: bool = True) -> None:
    print()
    line = (
        f"Bankroll EUR {_eur(config.bankroll_eur)}   "
        f"{config.tables} tables   "
        f"ruin tolerance {config.ruin_tolerance:.2%}"
    )
    # The Kelly fraction plays no part in the mix answer, so it is not shown
    # there - it would only invite the reader to look for where it applies.
    if kelly_fraction:
        line += f"   Kelly k={config.kelly_fraction:g}"
    print(line)
    notes = []
    if config.rakeback_pct:
        notes.append(f"rakeback {config.rakeback_pct:.0%}")
    if config.winrate_haircut_bb_per_table:
        notes.append(
            f"win rate haircut {config.winrate_haircut_bb_per_table:g} bb/100 per extra table"
        )
    if config.table_correlation:
        notes.append(f"table correlation {config.table_correlation:g}")
    if notes:
        print("In play: " + "; ".join(notes))


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


def cmd_mix(config: Config, output_dir: Path) -> int:
    """The main event: which distribution of tables across stakes is best.

    Prints both tables and writes each as a CSV. The CSVs are unconditional -
    they cost nothing, need no dependency, and a table you can only read in a
    terminal is a table you cannot pivot.
    """
    _print_header(config, kelly_fraction=False)

    # ---- Step 1: price each stake alone, and drop the redundant ones -------- #
    screens = mix.screen_stakes(config)
    print()
    print(f"STEP 1 - STAKE SCREEN   (if all {config.tables} tables were at one stake)")
    print()
    header = (
        f"  {'stake':<9}  {'bb/100':>7}  {'+RB':>6}  {'=net':>7}  {'hands':>9}  "
        f"{'+/- 95%':>8}  {'EUR/hr':>8}  {'EUR/100':>9}  {'sd EUR/100':>11}   verdict"
    )
    print(header)
    print(_rule(len(header) + 26))
    for screen in screens:
        verdict = "keep" if screen.kept else f"EXCLUDED - {screen.excluded_reason}"
        stake = screen.stake
        # The interval sits beside the win rate on purpose: a bb/100 figure with
        # no sample behind it is the single easiest way to misread this table.
        if stake.hands:
            margin = f"{estimation.winrate_ci(0.0, stake.stdev_bb100, stake.hands)[1]:>8.1f}"
            hands = f"{stake.hands:>9,}"
        else:
            margin, hands = f"{'?':>8}", f"{'-':>9}"
        rakeback = rates.rakeback_bb100(stake.rake_bb100, config.rakeback_pct)
        net = screen.mean_eur_per_100 / stake.bb_eur
        print(
            f"  {stake.name:<9}  {stake.winrate_bb100:>7.2f}  {rakeback:>6.2f}  {net:>7.2f}  "
            f"{hands}  {margin}  {screen.eur_per_hour:>8,.0f}  "
            f"{screen.mean_eur_per_100:>9,.2f}  {screen.stdev_eur_per_100:>11,.0f}   {verdict}"
        )
    kept = [s for s in screens if s.kept]
    print()

    # ---- Step 2: the frontier over what survived --------------------------- #
    try:
        allocations = mix.all_allocations(config)
    except mix.AllocationLimit as exc:
        print(f"cannot enumerate allocations: {exc}", file=sys.stderr)
        return 2

    best = mix.best_allocation(allocations)
    edge = mix.frontier(allocations)

    print(f"STEP 2 - EFFICIENT FRONTIER   ({len(edge)} undominated mixes over "
          f"{len(kept)} stakes)")
    print()
    header = f"  {'EUR/hr':>8}  {'ruin':>9}  {'P(-50%)':>8}  mix"
    print(header)
    print(_rule(len(header) + 26))
    for allocation in edge:
        marker = ""
        if best is not None and allocation.counts == best.counts:
            marker = "  <- BEST INSIDE TOLERANCE"
        print(
            f"  {allocation.eur_per_hour:>8,.0f}  {allocation.risk_of_ruin:>9.2%}  "
            f"{allocation.drawdown_50:>8.1%}  {allocation.label}{marker}"
        )
    print()
    print("  Downswing figures need a simulation and a timescale - they are in the deck,")
    print(f"  over {config.timescale_hands:,} hands. Simulating every frontier row here")
    print("  would turn an instant command into a slow one.")
    print()

    if best is None:
        cheapest = min(allocations, key=lambda a: a.risk_of_ruin)
        print(f"Nothing clears your tolerance. Safest available: {cheapest.label}, "
              f"at {cheapest.risk_of_ruin:.2%}.")
        print()

    _WRITTEN.extend(export.write_tables(screens, edge, config, best, output_dir))
    return 0


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
        "--output",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="where the CSVs and charts go (default: output/)",
    )
    common.add_argument(
        "--charts",
        action="store_true",
        default=argparse.SUPPRESS,
        help="also render the frontier PNG",
    )
    common.add_argument(
        "--deck",
        action="store_true",
        default=argparse.SUPPRESS,
        help="also build the PowerPoint deck",
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
    return parser


DEFAULT_ARGV = ["mix", "--charts", "--deck"]
"""What a bare `run.bat` does: everything - text, CSVs, chart and deck.

Running with no arguments should refresh every output, not silently skip some
and leave them stale on disk. Naming a subcommand opts out of rendering; the
CSVs are written either way, since they are free.
"""

DEFAULT_OUTPUT_DIR = Path("output")


def main(argv: list[str] | None = None) -> int:
    _WRITTEN.clear()  # module-level, so a second call in one process starts clean
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
    output_dir = get("output") or DEFAULT_OUTPUT_DIR

    exit_code = 0
    if command == "mix":
        exit_code = cmd_mix(config, output_dir)
    elif command == "report":
        cmd_report(config, reports)
    elif command == "stake":
        exit_code = cmd_stake(config, reports, args.name)

    # Both imported lazily, so the text commands need neither matplotlib nor
    # python-pptx installed.
    if get("charts"):
        from . import charts

        _WRITTEN.extend(charts.write_all(config, output_dir))

    plain_deck = False
    if get("deck"):
        from . import deck, pptx_common

        _WRITTEN.append(deck.build(config, output_dir))
        plain_deck = not pptx_common.template_available()

    # Reported once, at the end, so the numbered steps read in order rather than
    # being interleaved with file-written chatter.
    if _WRITTEN:
        print(f"\nFiles written to {output_dir.resolve()}:")
        for path in _WRITTEN:
            print(f"  {path.name}")
        if plain_deck:
            print("  (deck built without the branded template - "
                  "assets/deck_template.pptx is missing, so the styling is plain)")
        print()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
