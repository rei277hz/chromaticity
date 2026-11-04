"""Concrete expression evaluation used only to replay proof counterexamples."""

import ast
from dataclasses import replace
import operator


class Evaluator:
    def __init__(self, module, requirements, schema):
        self.module = module
        self.requirements = requirements
        self.schema = schema
        self.parsed = {}

    def expression(self, text, env):
        if text not in self.parsed:
            self.parsed[text] = ast.parse(text, mode="eval").body
        return self._expr(self.parsed[text], env)

    def _expr(self, node, env):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if node.id in self.schema["constants"]:
                return self.schema["constants"][node.id]
            raise ValueError("Unknown contract variable: " + node.id)
        if isinstance(node, ast.Attribute):
            value = self._expr(node.value, env)
            name = type(value).__name__
            if name not in self.schema["records"] or node.attr not in self.schema["records"][name]:
                raise ValueError("Invalid contract attribute")
            return getattr(value, node.attr)
        if isinstance(node, ast.Tuple):
            return tuple(self._expr(item, env) for item in node.elts)
        if isinstance(node, ast.Subscript):
            return self._expr(node.value, env)[self._expr(node.slice, env)]
        if isinstance(node, ast.UnaryOp):
            function = {
                ast.Not: operator.not_,
                ast.USub: operator.neg,
                ast.UAdd: operator.pos,
            }.get(type(node.op))
            if function is None:
                raise ValueError("Invalid unary operator")
            return function(self._expr(node.operand, env))
        if isinstance(node, ast.BinOp):
            function = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
            }.get(type(node.op))
            if function is None:
                raise ValueError("Invalid binary operator")
            return function(self._expr(node.left, env), self._expr(node.right, env))
        if isinstance(node, ast.BoolOp):
            for item in node.values:
                value = self._expr(item, env)
                if type(value) is not bool:
                    raise ValueError("Expected Boolean contract expression")
                if isinstance(node.op, ast.And) and not value or isinstance(node.op, ast.Or) and value:
                    return value
            return value
        if isinstance(node, ast.Compare):
            left = self._expr(node.left, env)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._expr(comparator, env)
                function = {
                    ast.Eq: operator.eq,
                    ast.NotEq: operator.ne,
                    ast.Is: operator.is_,
                    ast.IsNot: operator.is_not,
                    ast.Lt: operator.lt,
                    ast.LtE: operator.le,
                    ast.Gt: operator.gt,
                    ast.GtE: operator.ge,
                    ast.In: lambda a, b: a in b,
                    ast.NotIn: lambda a, b: a not in b,
                }.get(type(op))
                if function is None:
                    raise ValueError("Invalid comparison")
                if not function(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            branch = node.body if self._expr(node.test, env) else node.orelse
            return self._expr(branch, env)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "replace":
                function = replace
            elif name == "len":
                function = len
            elif name in self.schema["functions"] or name in self.schema["records"]:
                function = getattr(self.module, name)
            else:
                raise ValueError("Invalid contract call")
            return function(
                *[self._expr(item, env) for item in node.args],
                **{item.arg: self._expr(item.value, env) for item in node.keywords},
            )
        raise ValueError("Unsupported contract expression")
