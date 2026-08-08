"""Pytest configuration.

`backend/app.py` imports its agents as `from agents.fundamental import ...`,
which means it expects `backend/` on the import path rather than being a
package rooted at the repository. Putting `backend/` on `sys.path` here keeps
the tests using the same import convention as the application instead of
forcing a restructure.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
