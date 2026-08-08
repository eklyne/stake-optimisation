"""Analytic bankroll / stake-selection calculator.

Closed-form Kelly, risk-of-ruin and estimation maths for choosing what stakes to
play. Everything is reported in euros; win rates arrive in bb/100 because that is
the unit the data comes in.

The maths modules (`kelly`, `ruin`, `estimation`, `rates`) take and return plain
floats and know nothing about config objects, so a later Monte Carlo can import
them directly as its oracle.
"""

__version__ = "0.1.0"
