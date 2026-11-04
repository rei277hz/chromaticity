"""A deliberately small, fail-closed Python source model."""

import ast
from dataclasses import dataclass


class VerificationError(ValueError):
    pass


@dataclass(frozen=True)
class Type:
    kind: str
    args: tuple = ()


@dataclass(frozen=True)
class Record:
    name: str
    fields: dict


def docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str


INTRINSICS = {'len'}


class Source:
    def __init__(self, text):
        try:
            self.tree = ast.parse(text)
            compile(self.tree, "<automaton>", "exec")
        except SyntaxError as error:
            raise VerificationError(str(error)) from error
        self.records = {}
        self.defaults = {}
        self.functions = {}
        self.constants = {}
        self.signatures = {}
        self.locals = {}
        self.imports = set()
        for index, node in enumerate(self.tree.body):
            if index == 0 and docstring(node):
                continue
            if isinstance(node, ast.ImportFrom):
                allowed = {"dataclasses": {"dataclass", "replace"}, "typing": {"Literal", "Optional"}, "__future__": {"annotations"}}
                if node.level or node.module not in allowed or any(x.asname or x.name not in allowed[node.module] for x in node.names):
                    raise VerificationError("Only explicit dataclasses/typing imports are supported")
                self.imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ClassDef):
                if node.name in self.records:
                    raise VerificationError("Duplicate record " + node.name)
                self.records[node.name] = node
            elif isinstance(node, ast.FunctionDef):
                if node.name in self.functions:
                    raise VerificationError("Duplicate function " + node.name)
                self.functions[node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) != 1 or not isinstance(targets[0], ast.Name):
                    raise VerificationError("Only named literal module constants are supported")
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError) as error:
                    raise VerificationError("Module constants must be literal") from error
                if type(value) not in (int, bool, str, type(None)):
                    raise VerificationError("Module constants must be int, bool, str, or None")
                if targets[0].id in self.constants:
                    raise VerificationError("Duplicate module constant")
                self.constants[targets[0].id] = value
            else:
                raise VerificationError("Unsupported module syntax: " + type(node).__name__)
        names = [*self.records, *self.functions, *self.constants]
        if len(names) != len(set(names)) or any(n in {"replace", "dataclass", "Literal", "Optional", "int", "bool", "str", "tuple", "ValueError", *INTRINSICS} for n in names):
            raise VerificationError("Duplicate or reserved declaration name")
        for name, node in list(self.records.items()):
            if node.bases or node.keywords or len(node.decorator_list) != 1:
                raise VerificationError("Records must be frozen dataclasses without inheritance")
            dec = node.decorator_list[0]
            if "dataclass" not in self.imports or not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Name) or dec.func.id != "dataclass" or dec.args:
                raise VerificationError("Records must use @dataclass(frozen=True)")
            flags = {k.arg: ast.literal_eval(k.value) for k in dec.keywords}
            if len(flags) != len(dec.keywords) or flags.get("frozen") is not True or set(flags) - {"frozen", "slots"} or any(type(v) is not bool for v in flags.values()):
                raise VerificationError("Records must use @dataclass(frozen=True)")
            fields, defaults = {}, {}
            for index, field in enumerate(node.body):
                if isinstance(field, ast.Pass) or index == 0 and docstring(field):
                    continue
                if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
                    raise VerificationError("Record bodies contain only annotated fields")
                if field.target.id in fields:
                    raise VerificationError("Duplicate record field")
                fields[field.target.id] = self.annotation(field.annotation)
                if field.value is not None:
                    self.validate_expression(field.value)
                    defaults[field.target.id] = field.value
                elif defaults:
                    raise VerificationError("Required record field follows a default")
            self.records[name] = fields
            self.defaults[name] = defaults
        for name, node in self.functions.items():
            a = node.args
            if node.decorator_list or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg:
                raise VerificationError("Functions use plain typed positional/keyword parameters")
            signature = {arg.arg: self.annotation(arg.annotation) for arg in a.args}
            if len(signature) != len(a.args) or any(arg in self.functions or arg in self.records or arg in {"replace", "result", *INTRINSICS} for arg in signature):
                raise VerificationError("Duplicate or reserved argument name")
            self.signatures[name] = (signature, self.annotation(node.returns))
            local_names = set(signature)
            for statement in ast.walk(node):
                if isinstance(statement, ast.Name) and isinstance(statement.ctx, ast.Store):
                    local_names.add(statement.id)
            self.locals[name] = local_names
            for default in a.defaults:
                self.validate_expression(default)
            self.validate_statements(node.body)
        self._check_cycles()
        self._check_declaration_order()

    def annotation(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return self.annotation(ast.parse(node.value, mode="eval").body)
        if isinstance(node, ast.Name):
            if node.id in ("int", "bool", "str"):
                return Type(node.id)
            if node.id in self.records:
                return Type("record", (node.id,))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            members = (self.annotation(node.left), self.annotation(node.right))
            if set(members) != {Type('int'), Type('str')}:
                raise VerificationError('Only the exact int | str identity union is supported')
            return Type('union', (Type('int'), Type('str')))
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if node.value.id == "Optional":
                if "Optional" not in self.imports or len(items) != 1:
                    raise VerificationError("Optional requires one scalar type")
                element = self.annotation(items[0])
                if element.kind not in ("str", "int", "bool"):
                    raise VerificationError("Optional supports str, int, and bool")
                return Type("optional", (element,))
            if node.value.id == "Literal":
                if "Literal" not in self.imports:
                    raise VerificationError("Literal must be explicitly imported")
                try:
                    literals = tuple(ast.literal_eval(x) for x in items)
                except (ValueError, TypeError) as error:
                    raise VerificationError("Literal alternatives must be constants") from error
                if not literals or len(set(literals)) != len(literals) or any(type(x) not in (int, bool, str) for x in literals) or len({type(x) for x in literals}) != 1:
                    raise VerificationError("Literal alternatives require one scalar type")
                return Type("literal", literals)
            if node.value.id == "tuple":
                if len(items) == 2 and isinstance(items[1], ast.Constant) and items[1].value is Ellipsis:
                    return Type('sequence', (self.annotation(items[0]),))
                return Type("tuple", tuple(self.annotation(x) for x in items))
        raise VerificationError("Unsupported or missing type annotation: " + ast.dump(node) if node is not None else "Missing type annotation")

    def validate_expression(self, node):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            raise VerificationError("Collection slices belong in trusted runtime code")
        allowed = (ast.Constant, ast.Name, ast.Attribute, ast.Tuple, ast.Subscript, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call)
        if not isinstance(node, allowed):
            raise VerificationError("Unsupported expression: " + type(node).__name__)
        if isinstance(node, ast.Constant) and type(node.value) not in (int, bool, str, type(None)):
            raise VerificationError("Unsupported literal")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise VerificationError("Private attributes are not supported")
        if isinstance(node, ast.BinOp) and not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
            raise VerificationError("Unsupported binary operator")
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            raise VerificationError("Unsupported unary operator")
        if isinstance(node, ast.BoolOp) and not isinstance(node.op, (ast.And, ast.Or)):
            raise VerificationError("Unsupported Boolean operator")
        if isinstance(node, ast.Compare) and any(not isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)) for op in node.ops):
            raise VerificationError("Unsupported comparison")
        if isinstance(node, ast.Compare):
            left = node.left
            for op, right in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Is, ast.IsNot)) and not (
                        isinstance(left, ast.Constant) and left.value is None
                        or isinstance(right, ast.Constant) and right.value is None):
                    raise VerificationError("Identity comparisons are supported only with None")
                left = right
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in {*self.functions, *self.records, "replace", *INTRINSICS}:
                raise VerificationError("Only source-defined pure functions and constructors may be called")
            if node.func.id == "replace" and "replace" not in self.imports:
                raise VerificationError("replace must be explicitly imported")
            if any(k.arg is None for k in node.keywords) or len({k.arg for k in node.keywords}) != len(node.keywords):
                raise VerificationError("Expanded or duplicate keyword arguments are unsupported")
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.validate_expression(child)
            elif isinstance(child, ast.keyword):
                self.validate_expression(child.value)

    def validate_statements(self, statements):
        for index, node in enumerate(statements):
            if isinstance(node, ast.Pass) or index == 0 and docstring(node):
                continue
            if isinstance(node, ast.Return):
                if node.value is None:
                    raise VerificationError("Returns must have a value")
                self.validate_expression(node.value)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) != 1:
                    raise VerificationError("Chained assignment is unsupported")
                names = targets[0].elts if isinstance(targets[0], ast.Tuple) else [targets[0]]
                if any(not isinstance(n, ast.Name) or n.id in {*self.functions, *self.records, "replace", "result", *INTRINSICS} for n in names):
                    raise VerificationError("Assignments must bind local names")
                self.validate_expression(node.value)
                if isinstance(node, ast.AnnAssign):
                    self.annotation(node.annotation)
            elif isinstance(node, ast.If):
                self.validate_expression(node.test)
                self.validate_statements(node.body)
                self.validate_statements(node.orelse)
            elif isinstance(node, ast.Raise):
                call = node.exc
                if node.cause or not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != 'ValueError' or call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Constant) or type(call.args[0].value) is not str:
                    raise VerificationError('Only explicit ValueError with a literal message is supported')
            else:
                raise VerificationError("Unsupported statement: " + type(node).__name__)

    def _check_cycles(self):
        graph = {n: {c.func.id for c in ast.walk(f) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in self.functions} for n, f in self.functions.items()}
        def visit(name, stack):
            if name in stack:
                raise VerificationError("Recursive helper calls are unsupported")
            for child in graph[name]:
                visit(child, stack | {name})
        for name in graph:
            visit(name, set())
        def record_visit(name, stack):
            if name in stack:
                raise VerificationError("Recursive records are unsupported")
            def children(typ):
                if typ.kind == "record":
                    record_visit(typ.args[0], stack | {name})
                if typ.kind in ("tuple", "sequence", "union", "optional"):
                    for item in typ.args:
                        children(item)
            for typ in self.records[name].values():
                children(typ)
        for name in self.records:
            record_visit(name, set())

    def _check_declaration_order(self):
        bound = {"int", "bool", "str", "tuple"}
        postponed = "annotations" in self.imports
        def available(expression):
            if expression is None:
                return
            for part in ast.walk(expression):
                if isinstance(part, ast.Name) and part.id not in bound:
                    raise VerificationError("Declaration references an unbound name: " + part.id)
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom):
                bound.update(x.name for x in node.names)
            elif isinstance(node, ast.ClassDef):
                for decorator in node.decorator_list:
                    available(decorator)
                for field in node.body:
                    if isinstance(field, ast.Pass) or docstring(field):
                        continue
                    if not postponed:
                        available(field.annotation)
                    available(field.value)
                bound.add(node.name)
            elif isinstance(node, ast.FunctionDef):
                if not postponed:
                    available(node.returns)
                    for arg in node.args.args:
                        available(arg.annotation)
                for default in node.args.defaults:
                    available(default)
                bound.add(node.name)
            elif isinstance(node, ast.Assign):
                bound.add(node.targets[0].id)
            elif isinstance(node, ast.AnnAssign):
                bound.add(node.target.id)

    def expression(self, text):
        if not isinstance(text, str):
            raise VerificationError("Requirements expressions must be strings")
        try:
            node = ast.parse(text, mode="eval").body
        except SyntaxError as error:
            raise VerificationError(str(error)) from error
        self.validate_expression(node)
        return node

    def schema(self):
        def typ(t):
            return {"kind": t.kind, "args": [typ(x) for x in t.args] if t.kind in ("tuple", "sequence", "union", "optional") else list(t.args)}
        return {
            "records": {name: {key: typ(t) for key, t in fields.items()} for name, fields in self.records.items()},
            "functions": {name: {"arguments": {key: typ(t) for key, t in args.items()}, "returns": typ(ret)} for name, (args, ret) in self.signatures.items()},
            "constants": self.constants,
        }
