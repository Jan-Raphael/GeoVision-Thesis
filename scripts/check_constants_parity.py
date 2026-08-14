#!/usr/bin/env python3
"""Fail the build if `ai/` and `backend/` disagree about a shared constant.

``Progress-Calculation.md`` §9 names ``ai/progress/constants.py`` as the single
definition site for every threshold, "imported by both ``ai/`` and
``backend/``". That import cannot happen: the backend's base dependency group
deliberately excludes ``geovision-ai`` so the API process never loads torch
(ADR-011), and installing the package would drag torch in.

So a handful of values are necessarily restated in
``backend/app/domain/value_objects.py``, and this script is what keeps the
restatement honest. Drift between them is exactly the sort of defect that stays
invisible for months and then shows up as a thesis figure disagreeing with the
running system.

**It parses; it does not import.** No dependency on either package being
installed, no torch, no virtualenv, no risk of executing code to read a number.
It runs in well under a second in the `constraints` CI job, which needs nothing
but a bare Python.

    python scripts/check_constants_parity.py

Exit code 0 if every pair agrees, 1 otherwise, with the mismatch printed.
"""

from __future__ import annotations

import ast
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AI_CONSTANTS = ROOT / "ai" / "src" / "ai" / "progress" / "constants.py"
BACKEND_VALUE_OBJECTS = ROOT / "backend" / "app" / "domain" / "value_objects.py"

#: (ai module-level name, backend class, backend attribute).
#:
#: Only values that genuinely exist in both places belong here. Most constants
#: are needed by `ai/` alone; adding a row for one of those would force the
#: backend to carry a number it has no use for, which is worse duplication than
#: none at all.
PAIRS: tuple[tuple[str, str, str], ...] = (
    ("MACHINE_CEILING_PCT", "ProgressPct", "MACHINE_CEILING"),
    ("MIN_CONFIDENCE", "Confidence", "MIN_ELIGIBLE"),
)


def module_constants(path: Path) -> dict[str, Decimal]:
    """Extract module-level numeric assignments.

    Returns:
        Every ``NAME = <number>`` and ``NAME: Final = <number>`` found at module
        level, as ``Decimal`` so 80.0 and Decimal("80.00") compare equal.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, Decimal] = {}
    for node in tree.body:
        name, value = _assignment(node)
        if name is not None and value is not None:
            found[name] = value
    return found


def class_constants(path: Path, class_name: str) -> dict[str, Decimal]:
    """Extract numeric class attributes from one class in *path*.

    Handles ``Decimal("80.00")`` as well as bare numbers, because the backend
    uses ``Decimal`` throughout to keep percentages exact.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            found: dict[str, Decimal] = {}
            for statement in node.body:
                name, value = _assignment(statement)
                if name is not None and value is not None:
                    found[name] = value
            return found
    return {}


def _assignment(node: ast.stmt) -> tuple[str | None, Decimal | None]:
    """Pull ``(name, numeric value)`` out of an assignment statement."""
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id, _number(node.value)
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id, _number(node.value)
    return None, None


def _number(node: ast.expr | None) -> Decimal | None:
    """Evaluate a numeric literal or a ``Decimal("…")`` call.

    Deliberately narrow: anything more expressive would mean interpreting
    arbitrary code, and a threshold that needs computing does not belong in a
    constants file.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Decimal"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
    ):
        return Decimal(str(node.args[0].value))
    return None


def main() -> int:
    """Compare every declared pair and report any disagreement."""
    for path in (AI_CONSTANTS, BACKEND_VALUE_OBJECTS):
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            return 1

    ai_values = module_constants(AI_CONSTANTS)
    problems: list[str] = []

    for ai_name, backend_class, backend_attr in PAIRS:
        ai_value = ai_values.get(ai_name)
        backend_value = class_constants(BACKEND_VALUE_OBJECTS, backend_class).get(backend_attr)

        if ai_value is None:
            problems.append(f"{ai_name} not found in {AI_CONSTANTS.name}")
        elif backend_value is None:
            problems.append(
                f"{backend_class}.{backend_attr} not found in {BACKEND_VALUE_OBJECTS.name}"
            )
        elif ai_value != backend_value:
            problems.append(
                f"{ai_name} = {ai_value} but "
                f"{backend_class}.{backend_attr} = {backend_value}"
            )
        else:
            print(f"  ok  {ai_name} == {backend_class}.{backend_attr} == {ai_value}")

    if problems:
        print("\nShared constants disagree:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nai/src/ai/progress/constants.py is the definition site "
            "(Progress-Calculation.md §9). Update the backend to match, or "
            "change both deliberately.",
            file=sys.stderr,
        )
        return 1

    print(f"\n{len(PAIRS)} shared constant(s) agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
