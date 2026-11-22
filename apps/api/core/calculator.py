"""Constrained arithmetic evaluator for the agent calculator tool.

Only numeric literals and the operators ``+ - * / ** %`` plus parentheses and
unary signs are accepted. No names, attribute access, calls, comprehensions or
comparisons can reach ``eval``. Input length and exponent magnitude are capped.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

_MAX_LENGTH = 200
_MAX_EXPONENT = 1000

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorError(ValueError):
    """The expression is not a supported arithmetic expression."""


def evaluate(expression: str) -> float:
    if not isinstance(expression, str) or not expression.strip():
        raise CalculatorError("expression is required")
    expression = expression.strip()
    if len(expression) > _MAX_LENGTH:
        raise CalculatorError("expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError("invalid arithmetic expression") from exc

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](visit(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
                raise CalculatorError("exponent is too large")
            try:
                result = _BIN[type(node.op)](left, right)
            except (ZeroDivisionError, OverflowError, ValueError) as exc:
                raise CalculatorError(str(exc) or "arithmetic error") from exc
            if not math.isfinite(float(result)):
                raise CalculatorError("result is not a finite number")
            return float(result)
        raise CalculatorError("unsupported expression element")

    return visit(tree.body)
