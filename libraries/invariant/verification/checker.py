"""Generate proof obligations from source and a separate requirements file."""

import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from types import ModuleType

import z3

from .model import Source, Type, Record, VerificationError
from .symbolic import Interpreter, Sequence, Label, label_sort, IDENTITY, is_identity, is_text, boolean, equal


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def validate_requirements(source, requirements):
    required = {"version", "state", "event", "initializers", "step", "invariants"}
    allowed = required | {"contracts", "properties", "witnesses", "mutations", "description", "loops"}
    if not isinstance(requirements, dict) or set(requirements) - allowed or required - set(requirements):
        raise VerificationError("Missing or unknown requirements fields")
    if requirements["version"] != 1 or type(requirements["version"]) is not int:
        raise VerificationError("Unsupported requirements version")
    for key in ("state", "event"):
        if requirements[key] not in source.records:
            raise VerificationError("Unknown " + key + " record")
    if not requirements["initializers"] or not isinstance(requirements["initializers"], list):
        raise VerificationError("At least one initializer is required")
    for name in requirements["initializers"]:
        if name not in source.functions or source.signatures[name][1] != Type("record", (requirements["state"],)):
            raise VerificationError("Initializers must return the state record")
    step = requirements["step"]
    if step not in source.functions:
        raise VerificationError("Unknown transition function")
    parameters, returns = source.signatures[step]
    if list(parameters.values()) != [Type("record", (requirements["state"],)), Type("record", (requirements["event"],))]:
        raise VerificationError("Transition must take exactly (state, event)")
    if returns.kind != "tuple" or len(returns.args) != 2 or returns.args[0] != Type("record", (requirements["state"],)):
        raise VerificationError("Transition must return tuple[State, Effects]")
    invariants = requirements["invariants"]
    if not isinstance(invariants, dict) or not invariants or any(not isinstance(k, str) or not k for k in invariants):
        raise VerificationError("At least one named invariant is required")
    for expression in invariants.values():
        source.expression(expression)
    contracts = requirements.get("contracts", {})
    if not isinstance(contracts, dict):
        raise VerificationError("Contracts must be a mapping")
    for name, contract in contracts.items():
        if name not in source.functions or not isinstance(contract, dict) or set(contract) - {"requires", "ensures"}:
            raise VerificationError("Invalid function contract: " + name)
        for key in ("requires", "ensures"):
            if not isinstance(contract.get(key, []), list):
                raise VerificationError("Contract clauses must be lists")
            for expression in contract.get(key, []):
                source.expression(expression)
    loops = requirements.get('loops', [])
    if not isinstance(loops, list):
        raise VerificationError('Loop declarations must be a list')
    matched = set()
    loop_names = set()
    for loop in loops:
        if not isinstance(loop, dict) or set(loop) != {'name', 'function', 'target', 'iter', 'cursor', 'invariants', 'decreases'}:
            raise VerificationError('Invalid loop declaration')
        if loop['name'] in loop_names or not isinstance(loop['name'], str) or not loop['name']:
            raise VerificationError('Loop names must be unique')
        loop_names.add(loop['name'])
        function = source.functions.get(loop['function'])
        if function is None or not isinstance(loop['cursor'], str) or not loop['cursor'].isidentifier():
            raise VerificationError('Invalid loop function or cursor')
        selector = ast.dump(source.expression(loop['iter']))
        nodes = [node for node in ast.walk(function) if isinstance(node, ast.For) and ast.unparse(node.target) == loop['target'] and ast.dump(node.iter) == selector]
        if len(nodes) != 1 or id(nodes[0]) in matched:
            raise VerificationError('Loop selector must match exactly one unclaimed source loop')
        matched.add(id(nodes[0]))
        if not isinstance(loop['invariants'], list) or not loop['invariants']:
            raise VerificationError('Loop requires explicit invariants')
        for expression in [*loop['invariants'], loop['decreases']]:
            source.expression(expression)
    actual_loops = {id(node) for function in source.functions.values() for node in ast.walk(function) if isinstance(node, ast.For)}
    if matched != actual_loops:
        raise VerificationError('Every source loop requires a declaration')
    names = set()
    for kind in ("properties", "witnesses"):
        if not isinstance(requirements.get(kind, []), list):
            raise VerificationError(kind + " must be a list")
        for claim in requirements.get(kind, []):
            if not isinstance(claim, dict) or {"name", "assert"} - set(claim) or set(claim) - {"name", "variables", "assume", "lets", "assert"}:
                raise VerificationError("Invalid " + kind + " declaration")
            name = claim["name"]
            if not isinstance(name, str) or not name or name in names:
                raise VerificationError("Claim names must be unique and nonempty")
            names.add(name)
            if not isinstance(claim.get("variables", {}), dict) or not isinstance(claim.get("lets", {}), dict) or not isinstance(claim.get("assume", []), list):
                raise VerificationError("Invalid claim bindings")
            for key, typ in claim.get("variables", {}).items():
                if not key.isidentifier() or key in source.functions or key in source.records:
                    raise VerificationError("Invalid claim variable")
                source.annotation(ast.parse(typ, mode="eval").body)
            for key, expression in claim.get("lets", {}).items():
                if not key.isidentifier() or key in claim.get("variables", {}) or key in source.functions or key in source.records:
                    raise VerificationError("Invalid or duplicate let binding")
                source.expression(expression)
            for expression in [*claim.get("assume", []), claim["assert"]]:
                source.expression(expression)
    for mutation in requirements.get("mutations", []):
        if not isinstance(mutation, dict) or {"name", "function", "target", "replacement"} - set(mutation) or set(mutation) - {"name", "function", "target", "replacement", "detects"}:
            raise VerificationError("Invalid mutation declaration")
        if mutation["function"] not in source.functions or mutation["name"] in names:
            raise VerificationError("Unknown mutation function or duplicate name")
        names.add(mutation["name"])
        source.expression(mutation["target"])
        source.expression(mutation["replacement"])
        if not isinstance(mutation.get("detects", []), list) or any(not isinstance(x, str) for x in mutation.get("detects", [])):
            raise VerificationError("Mutation detects must list obligation names")


class Checker:
    def __init__(self, source, requirements, output=None, timeout_ms=5000, certificates=None):
        self.source = source
        self.requirements = requirements
        self.output = Path(output) if output is not None else None
        self.timeout_ms = timeout_ms
        self.obligations = []
        self.names = set()
        self.proved = set()
        self.models = {}
        self.replays = {}
        self.function_inputs = {}
        self.loop_replays = {}
        self.certificates = dict(certificates or {})

    def function_fingerprint(self, name):
        closure = {}
        def visit(function):
            if function in closure:
                return
            node = self.source.functions[function]
            contract = self.requirements.get('contracts', {}).get(function, {})
            loops = [loop for loop in self.requirements.get('loops', []) if loop['function'] == function]
            closure[function] = (ast.dump(node), contract, loops)
            expressions = [*contract.get('requires', []), *contract.get('ensures', [])]
            for loop in loops:
                expressions.extend([*loop['invariants'], loop['decreases']])
            if function == self.requirements['step']:
                expressions.extend(self.requirements['invariants'].values())
            trees = [node, *(self.source.expression(expression) for expression in expressions)]
            for tree in trees:
                for call in ast.walk(tree):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in self.source.functions:
                        visit(call.func.id)
        visit(name)
        declarations = [ast.dump(node) for node in self.source.tree.body if not isinstance(node, ast.FunctionDef)]
        return sha256(json.dumps((declarations, closure), sort_keys=True).encode())

    def interpreter(self):
        return Interpreter(self.source, self.requirements, summaries=self.proved)

    def solve(self, name, condition, expected="unsat", category="proof"):
        if name in self.names:
            raise VerificationError("Duplicate obligation name: " + name)
        self.names.add(name)
        solver = z3.Solver()
        solver.set(timeout=self.timeout_ms)
        solver.add(z3.simplify(boolean(condition)))
        answer = solver.check()
        item = {"name": name, "expected": expected, "actual": str(answer), "ok": str(answer) == expected, "category": category}
        if answer == z3.sat and expected == "unsat":
            self.models[name] = solver.model()
            item["counterexample"] = {str(d): str(solver.model()[d]) for d in solver.model().decls()}
        if answer == z3.unknown:
            item["reason"] = solver.reason_unknown()
        if self.output is not None:
            filename = f"{len(self.obligations):04d}-" + re.sub(r"[^A-Za-z0-9_.-]", "_", name) + ".smt2"
            directory = self.output / "obligations"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / filename).write_text("; " + name + "\n; expected " + expected + "\n" + solver.to_smt2())
            item["smt2"] = "obligations/" + filename
        self.obligations.append(item)
        return item

    def safety(self, name, interpreter, premises):
        for index, (label, condition) in enumerate(interpreter.loop_obligations):
            obligation = 'loop.' + name + '.' + str(index) + '.' + label
            if index < len(interpreter.loop_replays) and interpreter.loop_replays[index] is not None:
                self.loop_replays[obligation] = interpreter.loop_replays[index]
            self.solve(obligation, z3.And(premises, z3.Not(condition)))
        return self.solve("defined." + name, z3.And(premises, z3.Not(z3.And(*(condition for _, condition in interpreter.safety)))))

    def invariants(self, interpreter, state):
        return {name: boolean(interpreter.expression(expression, {"state": state})) for name, expression in self.requirements["invariants"].items()}

    def run(self):
        # Every function is checked, including helpers not reached by any property.
        order = []
        looping = set()
        def visit(name):
            if name in order:
                return
            for node in ast.walk(self.source.functions[name]):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.source.functions:
                    visit(node.func.id)
                    if node.func.id in looping:
                        looping.add(name)
                if isinstance(node, ast.For):
                    looping.add(name)
            order.append(name)
        for name in self.source.functions:
            visit(name)
        for name in order:
            parameters, _ = self.source.signatures[name]
            fingerprint = self.function_fingerprint(name)
            if name in looping and self.certificates.get(name) == fingerprint:
                # Only a proof from this same run and an identical transitive
                # source/schema/contract closure can authorize this reuse.
                self.solve('reuse.' + name, False, category='source_equivalence')
                self.proved.add(name)
                continue
            begin = len(self.obligations)
            i = self.interpreter()
            env = {key: i.symbol(name + "." + key, typ) for key, typ in parameters.items()}
            self.function_inputs[name] = env
            premises = []
            if name == self.requirements["step"]:
                premises.extend(self.invariants(i, next(iter(env.values()))).values())
            contract = self.requirements.get("contracts", {}).get(name, {})
            for expression in contract.get("requires", []):
                premises.append(boolean(i.expression(expression, env, z3.And(*premises))))
            assumptions_safety = list(i.safety)
            i.safety.clear()
            domain = z3.And(*i.domains)
            assumptions = z3.And(domain, *premises)
            self.solve("premise." + name, assumptions, "sat", "nonvacuity")
            if assumptions_safety:
                self.solve("defined.premise." + name, z3.And(domain, z3.Not(z3.And(*(p for _, p in assumptions_safety)))))
            result = i.call(name, [], env, check_preconditions=False)
            env["result"] = result
            if any(isinstance(node, ast.For) for node in ast.walk(self.source.functions[name])):
                conclusions = [(str(index) + '.return.' + str(number),
                                z3.Implies(path, boolean(i.expression(expression, env | {'result': value}, path))))
                               for index, expression in enumerate(contract.get('ensures', []))
                               for number, (path, value) in enumerate(i.return_paths[name])]
            else:
                conclusions = [(index, boolean(i.expression(expression, env))) for index, expression in enumerate(contract.get("ensures", []))]
            self.safety(name, i, assumptions)
            for index, conclusion in conclusions:
                self.solve(f"contract.{name}.{index}", z3.And(assumptions, *i.assumptions, z3.Not(conclusion)))
            if name in looping and contract.get('ensures') and all(item['ok'] for item in self.obligations[begin:]):
                self.proved.add(name)
                self.certificates[name] = fingerprint

        for name in self.requirements["initializers"]:
            i = self.interpreter()
            env = {key: i.symbol("init." + key, typ) for key, typ in self.source.signatures[name][0].items()}
            premises = []
            for expression in self.requirements.get("contracts", {}).get(name, {}).get("requires", []):
                premises.append(boolean(i.expression(expression, env, z3.And(*premises))))
            result = i.call(name, [], env)
            invariants = self.invariants(i, result)
            assumptions = z3.And(*i.domains, *premises)
            self.safety("init." + name, i, assumptions)
            for invariant, conclusion in invariants.items():
                self.solve("init." + name + "." + invariant, z3.And(assumptions, *i.assumptions, z3.Not(conclusion)))

        event_type = self.source.records[self.requirements["event"]]
        tag = event_type.get("kind")
        variants = tag.args if tag and tag.kind == "literal" else (None,)
        for variant in variants:
            i = self.interpreter()
            state = i.symbol("state", Type("record", (self.requirements["state"],)))
            event = i.symbol("event", Type("record", (self.requirements["event"],)))
            if variant is not None:
                event = Record(event.name, event.fields | {'kind': variant})
            premises = list(self.invariants(i, state).values())
            if variant is not None:
                premises.append(equal(event.fields["kind"], variant))
            step_name = self.requirements['step']
            arguments = dict(zip(self.source.signatures[step_name][0], (state, event)))
            for expression in self.requirements.get('contracts', {}).get(step_name, {}).get('requires', []):
                premises.append(boolean(i.expression(expression, arguments, z3.And(*premises))))
            result = i.call(self.requirements["step"], [state, event], {})
            conclusions = self.invariants(i, result[0])
            assumptions = z3.And(*i.domains, *premises)
            label = "all" if variant is None else str(variant)
            self.solve("premise.event." + label, assumptions, "sat", "nonvacuity")
            self.safety("event." + label, i, assumptions)
            for invariant, conclusion in conclusions.items():
                self.solve("preserve." + label + "." + invariant, z3.And(assumptions, *i.assumptions, z3.Not(conclusion)))

        for kind in ("properties", "witnesses"):
            for claim in self.requirements.get(kind, []):
                i = self.interpreter()
                env = {key: i.symbol(key, self.source.annotation(ast.parse(typ, mode="eval").body)) for key, typ in claim.get("variables", {}).items()}
                inputs = dict(env)
                # Assumptions are evaluated before lets: their domain establishes
                # the preconditions of actual implementation calls in the lets.
                premises = []
                for expression in claim.get("assume", []):
                    premises.append(boolean(i.expression(expression, env, z3.And(*premises))))
                assumption_safety = list(i.safety)
                i.safety.clear()
                for key, expression in claim.get("lets", {}).items():
                    env[key] = i.expression(expression, env)
                conclusion = boolean(i.expression(claim["assert"], env))
                assumptions = z3.And(*i.domains, *premises)
                prefix = "property." if kind == "properties" else "witness."
                name = prefix + claim["name"]
                if assumption_safety:
                    self.solve("defined.premise." + name, z3.And(*i.domains, z3.Not(z3.And(*(p for _, p in assumption_safety)))))
                self.solve("premise." + name, assumptions, "sat", "nonvacuity")
                self.safety(name, i, assumptions)
                if kind == "properties":
                    self.solve(name, z3.And(assumptions, *i.assumptions, z3.Not(conclusion)))
                    self.replays[name] = (claim, inputs)
                else:
                    self.solve(name, z3.And(assumptions, *i.assumptions, conclusion), "sat", "witness")
        return self.obligations


def _mutate(source, mutation):
    tree = copy.deepcopy(source.tree)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == mutation["function"])
    target = ast.dump(source.expression(mutation["target"]), include_attributes=False)
    matches = [node for node in ast.walk(function) if isinstance(node, ast.expr) and ast.dump(node, include_attributes=False) == target]
    if len(matches) != 1:
        raise VerificationError("Mutation selector must match exactly once: " + mutation["name"] + f" ({len(matches)} matches)")
    class Replace(ast.NodeTransformer):
        def visit(self, node):
            if node is matches[0]:
                return ast.copy_location(source.expression(mutation["replacement"]), node)
            return super().visit(node)
    return Source(ast.unparse(ast.fix_missing_locations(Replace().visit(tree))))


def verifier_identity():
    directory = Path(__file__).parent
    return {p.name: sha256(p.read_bytes()) for p in sorted(directory.glob("*.py"))}


def solver_identity():
    directory = Path(z3.__file__).parent
    binaries = sorted([*(directory / "lib").glob("libz3.so*"), *(directory / "lib").glob("libz3*.dylib")])
    if not binaries:
        raise VerificationError("Cannot identify the packaged Z3 shared library")
    return {name: sha256((directory / name).read_bytes()) for name in ("z3.py", "z3core.py")} | {"libz3": sha256(binaries[0].read_bytes())}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError("Duplicate requirements key: " + key)
        value[key] = item
    return value


def _decode_model_value(model, value, module):
    from .model import Record
    if isinstance(value, Record):
        return getattr(module, value.name)(**{key: _decode_model_value(model, item, module) for key, item in value.fields.items()})
    if isinstance(value, tuple):
        return tuple(_decode_model_value(model, item, module) for item in value)
    if isinstance(value, Label):
        constructors = label_sort(value.alternatives)[1]
        actual = model.eval(value.value, model_completion=True)
        return value.alternatives[next(index for index, constructor in enumerate(constructors) if actual.eq(constructor))]
    if isinstance(value, Sequence):
        length = model.eval(value.length, model_completion=True).as_long()
        # This is a diagnostic resource bound, never a proof-domain restriction.
        if not 0 <= length <= 1000000:
            raise VerificationError('Counterexample is too large to replay')
        return tuple(_decode_model_value(model, value.values[index], module) for index in range(length))
    if type(value) in (bool, int, str):
        return value
    if is_identity(value):
        if z3.is_true(model.eval(IDENTITY.is_integer_identity(value), model_completion=True)):
            return _decode_model_value(model, IDENTITY.integer_value(value), module)
        return _decode_model_value(model, IDENTITY.text_value(value), module)
    if is_text(value):
        length = model.eval(z3.Length(value), model_completion=True).as_long()
        if not 0 <= length <= 1000000:
            raise VerificationError('Counterexample text is too large to replay')
        return ''.join(chr(model.eval(value[index], model_completion=True).as_long()) for index in range(length))
    concrete = model.eval(value, model_completion=True)
    if z3.is_int_value(concrete):
        return concrete.as_long()
    if z3.is_true(concrete) or z3.is_false(concrete):
        return z3.is_true(concrete)
    raise VerificationError('Counterexample did not decode concretely')


def replay(checker, names):
    from .runtime_contracts import Contract
    module = ModuleType('_invariant_mutation_' + str(id(checker)))
    sys.modules[module.__name__] = module
    try:
        exec(compile(checker.source.tree, '<checked mutation>', 'exec'), module.__dict__)
        evaluator = Contract(module, checker.requirements, checker.source.schema())
        cases = []
        for name in names:
            model = checker.models.get(name)
            if model is None:
                return {'ok': False, 'reason': 'Concrete replay requires a SAT obligation', 'cases': cases}
            if name in checker.replays:
                claim, symbolic = checker.replays[name]
                env = {key: _decode_model_value(model, value, module) for key, value in symbolic.items()}
                original = dict(env)
                if any(evaluator.expression(expression, env) is not True for expression in claim.get('assume', [])):
                    return {'ok': False, 'reason': 'Counterexample premises did not replay', 'cases': cases}
                for key, expression in claim.get('lets', {}).items():
                    env[key] = evaluator.expression(expression, env)
                if evaluator.expression(claim['assert'], env) is not False:
                    return {'ok': False, 'reason': 'Counterexample conclusion did not replay', 'cases': cases}
                cases.append({'obligation': name, 'inputs': {key: repr(value) for key, value in original.items()}, 'counterexample': True})
                continue
            if name in checker.loop_replays:
                context = checker.loop_replays[name]
                function = context['function']
                arguments = {key: _decode_model_value(model, value, module)
                             for key, value in context['arguments'].items()}
                if function not in checker.requirements.get('contracts', {}):
                    return {'ok': False, 'reason': 'Loop replay requires an independent function postcondition', 'cases': cases}
                ordered = [arguments[key] for key in checker.source.signatures[function][0]]
                result = getattr(module, function)(*ordered)
                failed = [expression for expression in checker.requirements['contracts'][function].get('ensures', [])
                          if evaluator.expression(expression, arguments | {'result': result}) is False]
                if not failed:
                    return {'ok': False, 'reason': 'Loop counterexample did not violate the function postcondition', 'cases': cases}
                cases.append({'obligation': name, 'function': function,
                              'inputs': {key: repr(value) for key, value in arguments.items()},
                              'counterexample': True, 'failed_postconditions': failed})
                continue
            if name.startswith('contract.'):
                parts = name.split('.')
                function, clause = parts[1], int(parts[2])
                if function not in checker.function_inputs:
                    return {'ok': False, 'reason': 'Contract replay inputs are unavailable', 'cases': cases}
                symbolic = checker.function_inputs[function]
                inputs = {key: _decode_model_value(model, value, module) for key, value in symbolic.items()}
                arguments = [inputs[key] for key in checker.source.signatures[function][0]]
                result = getattr(module, function)(*arguments)
                postcondition = checker.requirements['contracts'][function]['ensures'][clause]
                if evaluator.expression(postcondition, inputs | {'result': result}) is not False:
                    return {'ok': False, 'reason': 'Contract counterexample did not replay', 'cases': cases}
                cases.append({'obligation': name, 'function': function, 'inputs': {key: repr(value) for key, value in inputs.items()}, 'counterexample': True})
                continue
            return {'ok': False, 'reason': 'Concrete replay has no independent assertion for ' + name, 'cases': cases}
        return {'ok': bool(cases), 'cases': cases}
    except (ValueError, TypeError, ArithmeticError, IndexError) as error:
        return {'ok': False, 'reason': str(error), 'cases': []}
    finally:
        sys.modules.pop(module.__name__, None)


def verify(source_path, requirements_path, output_path=None, timeout_ms=5000, required_properties=(), required_witnesses=(), required_mutations=()):
    if timeout_ms <= 0:
        raise VerificationError("Solver timeout must be positive")
    output = Path(output_path) if output_path is not None else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        for artifact in ("receipt.json", "validators.py"):
            (output / artifact).unlink(missing_ok=True)
    source_path, requirements_path = Path(source_path), Path(requirements_path)
    source_bytes, requirements_bytes = source_path.read_bytes(), requirements_path.read_bytes()
    source = Source(source_bytes.decode())
    try:
        requirements = json.loads(requirements_bytes, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as error:
        raise VerificationError(str(error)) from error
    validate_requirements(source, requirements)
    inventory = {}
    for kind, required in (('properties', required_properties), ('witnesses', required_witnesses), ('mutations', required_mutations)):
        if any(not isinstance(name, str) or not name for name in required):
            raise VerificationError('Required ' + kind + ' names must be nonempty strings')
        inventory['required_' + kind] = sorted(set(required))
        missing = set(required) - {claim['name'] for claim in requirements.get(kind, [])}
        if missing:
            raise VerificationError('Missing required ' + kind + ': ' + ', '.join(sorted(missing)))
    checker = Checker(source, requirements, output, timeout_ms)
    obligations = checker.run()
    controls = []
    for mutation in requirements.get("mutations", []):
        mutated = _mutate(source, mutation)
        validate_requirements(mutated, requirements)
        mutation_output = output / "mutations" / re.sub(r"[^A-Za-z0-9_.-]", "_", mutation["name"]) if output else None
        mutation_checker = Checker(mutated, requirements, mutation_output, timeout_ms, certificates=checker.certificates)
        checks = mutation_checker.run()
        failures = [item["name"] for item in checks if item["category"] == "proof" and item["expected"] == "unsat" and item["actual"] == "sat"]
        detects = mutation.get("detects", [])
        missing = set(detects) - {item["name"] for item in checks}
        if missing:
            raise VerificationError("Unknown mutation detection obligations: " + ", ".join(sorted(missing)))
        killed = bool(failures) and (not detects or all(name in failures for name in detects))
        if any(item["actual"] == "unknown" and (not detects or item["name"] in detects) for item in checks):
            killed = False
        replayed = replay(mutation_checker, detects or [name for name in failures if name.startswith('property.')]) if killed else {'ok': False, 'cases': []}
        controls.append({"name": mutation["name"], "ok": killed and replayed['ok'], "detected_by": failures, "obligations": checks, 'replay': replayed})
    report = {"version": 1, "ok": all(x["ok"] for x in obligations + controls), "solver": "Z3 " + z3.get_version_string(), **inventory, "obligations": obligations, "mutations": controls}
    if output is not None:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        if report["ok"]:
            receipt = {"version": 1, "source_sha256": sha256(source_bytes), "requirements_sha256": sha256(requirements_bytes), **inventory, "verifier_sha256": verifier_identity(), "solver": z3.get_version_string(), "solver_sha256": solver_identity(), "python": sys.version, "report_sha256": sha256((output / "report.json").read_bytes())}
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            validator = "# Generated from successfully verified source and requirements.\n_REQUIREMENTS = " + repr(requirements) + "\n_SCHEMA = " + repr(source.schema()) + "\n\ndef bind(module, *, binder=None):\n    if binder is None:\n        from invariant.verification.runtime_contracts import bind as binder\n    return binder(module, _REQUIREMENTS, _SCHEMA)\n"
            (output / "validators.py").write_text(validator)
    return report


def verify_receipt(source_path, requirements_path, receipt_path):
    receipt = json.loads(Path(receipt_path).read_text())
    return (receipt.get("version") == 1 and receipt.get("source_sha256") == sha256(Path(source_path).read_bytes()) and receipt.get("requirements_sha256") == sha256(Path(requirements_path).read_bytes()) and receipt.get("verifier_sha256") == verifier_identity() and receipt.get("solver") == z3.get_version_string() and receipt.get("solver_sha256") == solver_identity())
