"""Entry point: `python run.py [args]`.

Identical to `python -m shotopt` - it exists so the tool can be run by pointing
at a file, which is how everything else around here gets run.

    python run.py                     # best mix (the default)
    python run.py report              # per-stake table
    python run.py stake 200NL         # one stake in detail
    python run.py mix --charts        # + write the PNGs

Needs an interpreter with matplotlib for the charts. run.bat picks one that has
it; the text commands run on bare Python 3.11+.
"""

from shotopt.cli import main

raise SystemExit(main())
