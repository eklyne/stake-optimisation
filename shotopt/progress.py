"""A terminal progress bar, in about thirty lines and no dependencies.

The deck build simulates a few dozen million hands and takes the best part of a
minute. Without something moving on screen that is indistinguishable from a
hang, and the honest fix is to show the work rather than to make the wait
shorter by doing less of it.
"""

from __future__ import annotations

import shutil
import sys

__all__ = ["Progress"]


class Progress:
    """Single-line progress bar, redrawn in place.

    Writes to stderr so a piped or redirected run keeps clean stdout - the
    tables are data, this is chatter.

    Off a terminal, redrawing in place produces a wall of control characters, so
    it falls back to one plain line per step instead of disappearing entirely.
    Progress you cannot see in a logged or piped run is the case where you most
    want it.
    """

    def __init__(self, total: int, label: str = "", width: int = 34):
        self.total = max(total, 1)
        self.label = label
        self.width = width
        self.done = 0
        self.interactive = sys.stderr.isatty()
        self._last_line = ""

    def advance(self, note: str = "") -> None:
        self.done += 1
        self.draw(note)

    def draw(self, note: str = "") -> None:
        if not self.interactive:
            if self.done:  # one line per completed step, no redraws
                sys.stderr.write(f"  [{self.done:>2}/{self.total}] {note}\n")
                sys.stderr.flush()
            return
        filled = int(self.width * self.done / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        line = f"  [{bar}] {self.done:>2}/{self.total}  {note}"
        # Pad to erase the tail of a longer previous line, then trim to the
        # terminal so a long allocation label cannot wrap and leave debris.
        columns = shutil.get_terminal_size((100, 24)).columns - 1
        line = line[:columns].ljust(len(self._last_line))
        sys.stderr.write("\r" + line)
        sys.stderr.flush()
        self._last_line = line.rstrip()

    def close(self, note: str = "") -> None:
        if self.interactive:
            sys.stderr.write("\r" + " " * len(self._last_line) + "\r")
        if note:
            sys.stderr.write(f"  {note}\n")
        sys.stderr.flush()
