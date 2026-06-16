"""Meta-test: the clipping package must be declared so `pip install .` ships it.

Without this, `from ..clipping import ...` (in engine/scoring_fanout.py) raises
ModuleNotFoundError on the Railway build, where the source tree is installed, not
run in place.
"""

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_clipping_package_declared():
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    packages = data["tool"]["setuptools"]["packages"]
    assert "fliphouse_worker.clipping" in packages
