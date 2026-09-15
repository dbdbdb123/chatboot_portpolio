"""코드 실행 없이 제한된 AST에서 Decimal 사칙연산만 수행한다."""

import ast
import operator
import re
from decimal import Decimal, DecimalException, localcontext
from typing import Any

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.schemas.internal_tools import CalculateArguments
from backend.tools.registry import INTERNAL_SERVER

OPERATIONS = {ast.Add: operator.add, ast.Sub: operator.sub,
              ast.Mult: operator.mul, ast.Div: operator.truediv}


def calculate(expression: str) -> str:
    """최대 256자·128노드 수식. 소수 정밀도 28자리, 결과 절댓값 1e100 이하."""
    expression = expression.strip()
    if not expression or len(expression) > 256 or not re.fullmatch(r"[0-9.\s+*/()-]+", expression):
        raise ValueError("only decimal numbers, parentheses and + - * / are supported")
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 128:
            raise ValueError("expression is too complex")

        def evaluate(node: ast.AST) -> Decimal:
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = Decimal(ast.get_source_segment(expression, node))
            elif isinstance(node, ast.BinOp) and type(node.op) in OPERATIONS:
                value = OPERATIONS[type(node.op)](evaluate(node.left), evaluate(node.right))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand)
                if isinstance(node.op, ast.USub):
                    value = -value
            else:
                raise ValueError("unsupported expression")
            if not value.is_finite() or abs(value) > Decimal("1e100"):
                raise ValueError("calculation exceeds supported range")
            return value

        with localcontext() as context:
            context.prec = 28
            context.Emax = 100
            context.Emin = -100
            result = evaluate(tree.body)
            return str(result.normalize()) if result else "0"
    except (SyntaxError, DecimalException, RecursionError) as exc:
        raise ValueError("invalid arithmetic expression or division by zero") from exc


class CalculatorTool:
    @property
    def definition(self) -> MCPTool:
        return MCPTool(
            INTERNAL_SERVER, "calculate",
            "Calculate decimal arithmetic using + - * / and parentheses. "
            "For percentages use /100, e.g. 1250000*(1-15/100). "
            "No functions, powers or unit conversion. Precision: 28 significant digits.",
            CalculateArguments.model_json_schema(),
        )

    async def execute(self, arguments: dict[str, Any]) -> MCPToolResult:
        args = CalculateArguments.model_validate(arguments)
        return MCPToolResult(structured_content={
            "expression": args.expression, "result": calculate(args.expression),
        })
