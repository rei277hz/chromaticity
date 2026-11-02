"""Path-sensitive execution of the restricted handwritten Python subset."""

import ast
from dataclasses import dataclass
import hashlib
import z3

from .model import Record, Type, VerificationError, docstring


# Python strings are sequences of codepoints, including lone surrogates. Z3's
# StringVal escape syntax is not an injective encoding of Python text.
TEXT = z3.SeqSort(z3.IntSort())
_identity = z3.Datatype('InvariantIdentity')
_identity.declare('integer_identity', ('integer_value', z3.IntSort()))
_identity.declare('text_identity', ('text_value', TEXT))
IDENTITY = _identity.create()
_optional_text = z3.Datatype('InvariantOptionalText')
_optional_text.declare('optional_none')
_optional_text.declare('optional_some', ('optional_value', TEXT))
OPTIONAL_TEXT = _optional_text.create()
_LABELS = {}


@dataclass(frozen=True)
class Label:
    value: object
    alternatives: tuple


def label_sort(alternatives):
    if alternatives not in _LABELS:
        name = 'Labels_' + hashlib.sha256(repr(alternatives).encode('utf-8', 'surrogatepass')).hexdigest()[:24]
        _LABELS[alternatives] = z3.EnumSort(name, [name + '_' + str(i) for i in range(len(alternatives))])
    return _LABELS[alternatives]


def label_text(value):
    _, constructors = label_sort(value.alternatives)
    result = text_value(value.alternatives[-1])
    for alternative, constructor in reversed(list(zip(value.alternatives[:-1], constructors[:-1]))):
        result = z3.If(value.value == constructor, text_value(alternative), result)
    return result


def text_value(value):
    if type(value) is str:
        units = [z3.Unit(z3.IntVal(ord(c))) for c in value]
        return z3.Concat(*units) if len(units) > 1 else units[0] if units else z3.Empty(TEXT)
    return value


def is_text(value):
    return type(value) is str or isinstance(value, z3.ExprRef) and value.sort() == TEXT


def is_identity(value):
    return isinstance(value, z3.ExprRef) and value.sort() == IDENTITY


def is_optional_text(value):
    return isinstance(value, z3.ExprRef) and value.sort() == OPTIONAL_TEXT


def optional_text_value(value):
    if value is None:
        return OPTIONAL_TEXT.optional_none
    if is_optional_text(value):
        return value
    if isinstance(value, Label):
        value = label_text(value)
    if is_text(value):
        return OPTIONAL_TEXT.optional_some(text_value(value))
    raise VerificationError('Optional[str] requires str or None')


def identity_value(value):
    if isinstance(value, Label):
        return IDENTITY.text_identity(label_text(value))
    if is_identity(value):
        return value
    if type(value) is int or z3.is_int(value):
        return IDENTITY.integer_identity(value)
    if is_text(value):
        return IDENTITY.text_identity(text_value(value))
    raise VerificationError('Identity requires int or str, never bool')


@dataclass(frozen=True)
class Sequence:
    length: object
    values: object
    element: Type


@dataclass(frozen=True)
class Range:
    length: object


def boolean(value):
    if type(value) is bool:
        return z3.BoolVal(value)
    if z3.is_bool(value):
        return value
    raise VerificationError("Expected Boolean expression")


def integer(value):
    if type(value) is int:
        return z3.IntVal(value)
    if z3.is_int(value):
        return value
    raise VerificationError("Expected integer expression")


def modulo(left, right):
    """Normalize congruent polynomial operands under the same modulus.

    Removing inner reductions is exact in integer modular arithmetic. Keeping
    the outer reduction avoids nonlinear quotient reasoning in cyclic scans.
    Division and all other operations are deliberately opaque to this rewrite.
    """
    def lift(value):
        if z3.is_app(value):
            kind = value.decl().kind()
            if kind == z3.Z3_OP_MOD and value.arg(1).eq(right):
                return lift(value.arg(0))
            if kind in (z3.Z3_OP_ADD, z3.Z3_OP_SUB, z3.Z3_OP_MUL, z3.Z3_OP_UMINUS):
                return value.decl()(*(lift(child) for child in value.children()))
        return value
    return z3.simplify(lift(left) % right)


def equal(left, right):
    if isinstance(left, Label) or isinstance(right, Label):
        if isinstance(left, Label) and isinstance(right, Label) and left.alternatives == right.alternatives:
            return left.value == right.value
        if isinstance(left, Label) and type(right) is str:
            return left.value == label_sort(left.alternatives)[1][left.alternatives.index(right)] if right in left.alternatives else z3.BoolVal(False)
        if isinstance(right, Label) and type(left) is str:
            return equal(right, left)
        return equal(label_text(left) if isinstance(left, Label) else left, label_text(right) if isinstance(right, Label) else right)
    if left is None or right is None or is_optional_text(left) or is_optional_text(right):
        try:
            return optional_text_value(left) == optional_text_value(right)
        except VerificationError:
            return z3.BoolVal(False)
    if is_identity(left) or is_identity(right):
        identity, other = (left, right) if is_identity(left) else (right, left)
        if type(other) is bool or z3.is_bool(other):
            return z3.And(IDENTITY.is_integer_identity(identity), IDENTITY.integer_value(identity) == z3.If(other, 1, 0))
        try:
            return identity_value(left) == identity_value(right)
        except VerificationError:
            return z3.BoolVal(False)
    if isinstance(left, Sequence) or isinstance(right, Sequence):
        sequence, other = (left, right) if isinstance(left, Sequence) else (right, left)
        if isinstance(other, tuple):
            return z3.And(sequence.length == len(other), *(equal(sequence.values[index], item) for index, item in enumerate(other)))
        if not isinstance(left, Sequence) or not isinstance(right, Sequence):
            return z3.BoolVal(False)
        i = z3.FreshInt('equality.index')
        return z3.And(left.length == right.length, z3.ForAll(i, z3.Implies(z3.And(0 <= i, i < left.length), equal(left.values[i], right.values[i]))))
    if isinstance(left, Record) or isinstance(right, Record):
        if not isinstance(left, Record) or not isinstance(right, Record) or left.name != right.name:
            return z3.BoolVal(False)
        return z3.And(*(equal(left.fields[k], right.fields[k]) for k in left.fields))
    if isinstance(left, tuple) or isinstance(right, tuple):
        if not isinstance(left, tuple) or not isinstance(right, tuple) or len(left) != len(right):
            return z3.BoolVal(False)
        return z3.And(*(equal(a, b) for a, b in zip(left, right)))
    def sort(x):
        if type(x) is bool or z3.is_bool(x):
            return "bool"
        if type(x) is int or z3.is_int(x):
            return "int"
        if is_text(x):
            return "str"
        raise VerificationError("Invalid scalar")
    left_sort, right_sort = sort(left), sort(right)
    if {left_sort, right_sort} == {"bool", "int"}:
        a = z3.If(left, 1, 0) if left_sort == "bool" else left
        b = z3.If(right, 1, 0) if right_sort == "bool" else right
        return boolean(a == b)
    if left_sort != right_sort:
        return z3.BoolVal(False)
    return boolean(text_value(left) == text_value(right))


def fixed_tuple_element(values):
    kinds = set()
    for value in values:
        if isinstance(value, Label):
            kinds.add('str')
        elif is_identity(value):
            kinds.add('union')
        elif value is None or is_optional_text(value):
            kinds.add('optional')
        elif type(value) is bool or z3.is_bool(value):
            kinds.add('bool')
        elif type(value) is int or z3.is_int(value):
            kinds.add('int')
        elif is_text(value):
            kinds.add('str')
        else:
            return None
    if not kinds:
        return None
    if 'union' in kinds or {'int', 'str'} <= kinds:
        return Type('union')
    if kinds <= {'str', 'optional'}:
        return Type('optional', (Type('str'),))
    return Type(next(iter(kinds))) if len(kinds) == 1 else None


def empty_sequence(element):
    if element.kind == 'union':
        default = identity_value(0)
    elif element.kind == 'optional':
        default = OPTIONAL_TEXT.optional_none
    elif element.kind == 'str':
        default = text_value('')
    elif element.kind == 'bool':
        default = z3.BoolVal(False)
    else:
        default = z3.IntVal(0)
    return Sequence(z3.IntVal(0), z3.K(z3.IntSort(), default), element)


def choose(condition, yes, no):
    if isinstance(yes, (tuple, Record, Sequence)):
        # A concrete container branch must retain its declared representation;
        # coercing an unreachable alternative can introduce a narrower sequence
        # element type and falsely reject a concrete identity-ledger trace.
        selected = z3.simplify(boolean(condition))
        if z3.is_true(selected):
            return yes
        if z3.is_false(selected):
            return no
    if isinstance(yes, Label) or isinstance(no, Label):
        label = yes if isinstance(yes, Label) else no
        _, constructors = label_sort(label.alternatives)
        def convert(value):
            if isinstance(value, Label) and value.alternatives == label.alternatives:
                return value.value
            if type(value) is str and value in label.alternatives:
                return constructors[label.alternatives.index(value)]
            return None
        a, b = convert(yes), convert(no)
        if a is not None and b is not None:
            return Label(z3.If(condition, a, b), label.alternatives)
        return choose(condition, label_text(yes) if isinstance(yes, Label) else yes, label_text(no) if isinstance(no, Label) else no)
    if yes is None or no is None or is_optional_text(yes) or is_optional_text(no):
        return z3.If(condition, optional_text_value(yes), optional_text_value(no))
    if (is_text(yes) and (type(no) is int or z3.is_int(no))) or (is_text(no) and (type(yes) is int or z3.is_int(yes))):
        return z3.If(condition, identity_value(yes), identity_value(no))
    if is_identity(yes) or is_identity(no):
        return z3.If(condition, identity_value(yes), identity_value(no))
    if is_text(yes) and is_text(no):
        return z3.If(condition, text_value(yes), text_value(no))
    if isinstance(yes, tuple) and isinstance(no, tuple) and len(yes) != len(no):
        values = yes if yes else no
        if not values:
            raise VerificationError("Cannot infer an empty sequence element type")
        sample = values[0]
        if is_identity(sample):
            element = Type("union", (Type("int"), Type("str")))
            scalar = identity_value
            value_sort = IDENTITY
        elif is_text(sample):
            element = Type("str")
            scalar = text_value
            value_sort = TEXT
        elif type(sample) is int or z3.is_int(sample):
            element = Type("int")
            scalar = integer
            value_sort = z3.IntSort()
        elif type(sample) is bool or z3.is_bool(sample):
            element = Type("bool")
            scalar = boolean
            value_sort = z3.BoolSort()
        else:
            raise VerificationError("Cannot infer tuple sequence element type")

        def tuple_sequence(value):
            array = z3.K(z3.IntSort(), z3.FreshConst(value_sort, "sequence.default"))
            for index, item in enumerate(value):
                array = z3.Store(array, index, scalar(item))
            return Sequence(z3.IntVal(len(value)), array, element)

        left, right = tuple_sequence(yes), tuple_sequence(no)
        return Sequence(z3.If(condition, left.length, right.length),
                        z3.If(condition, left.values, right.values), element)
    if isinstance(yes, Sequence) or isinstance(no, Sequence):
        sequence = yes if isinstance(yes, Sequence) else no

        def as_sequence(value):
            if isinstance(value, Sequence):
                if value.element != sequence.element:
                    raise VerificationError("Incompatible sequence element types")
                return value
            if not isinstance(value, tuple):
                raise VerificationError("Incompatible sequence branch type")
            array_sort = sequence.values.sort()
            default = z3.FreshConst(array_sort.range(), "sequence.default")
            values = z3.K(array_sort.domain(), default)
            for index, item in enumerate(value):
                if sequence.element.kind == "union":
                    item = identity_value(item)
                elif sequence.element.kind == "str":
                    item = text_value(item)
                elif sequence.element.kind == "int":
                    item = integer(item)
                elif sequence.element.kind == "bool":
                    item = boolean(item)
                elif sequence.element.kind == "optional":
                    item = optional_text_value(item)
                values = z3.Store(values, index, item)
            return Sequence(z3.IntVal(len(value)), values, sequence.element)

        left, right = as_sequence(yes), as_sequence(no)
        return Sequence(z3.If(condition, left.length, right.length),
                        z3.If(condition, left.values, right.values),
                        sequence.element)
    if isinstance(yes, Sequence) and isinstance(no, Sequence) and yes.element == no.element:
        return Sequence(z3.If(condition, yes.length, no.length), z3.If(condition, yes.values, no.values), yes.element)
    if isinstance(yes, Record) and isinstance(no, Record) and yes.name == no.name:
        fields = {}
        for key in yes.fields:
            try:
                fields[key] = choose(condition, yes.fields[key], no.fields[key])
            except VerificationError as error:
                raise VerificationError(
                    f"Incompatible branch field {yes.name}.{key}: "
                    f"{type(yes.fields[key]).__name__} / {type(no.fields[key]).__name__}"
                ) from error
        return Record(yes.name, fields)
    if isinstance(yes, tuple) and isinstance(no, tuple) and len(yes) == len(no):
        return tuple(choose(condition, a, b) for a, b in zip(yes, no))
    if isinstance(yes, tuple) and isinstance(no, tuple):
        element = fixed_tuple_element((*yes, *no))
        if element is not None:
            seed = empty_sequence(element)
            left = choose(z3.BoolVal(True), seed, yes)
            right = choose(z3.BoolVal(True), seed, no)
            return Sequence(z3.If(condition, left.length, right.length),
                            z3.If(condition, left.values, right.values), element)
    if isinstance(yes, (tuple, Record)) or isinstance(no, (tuple, Record)):
        raise VerificationError("Incompatible branch result types")
    # Z3 coerces bool to int, whereas the accepted source subset has strict types.
    if (type(yes) is bool or z3.is_bool(yes)) != (type(no) is bool or z3.is_bool(no)):
        raise VerificationError("Incompatible branch result types")
    try:
        return z3.If(condition, yes, no)
    except z3.Z3Exception as error:
        raise VerificationError("Incompatible branch result types") from error


class Interpreter:
    def __init__(self, source, requirements, *, summaries=()):
        self.source = source
        self.local_types = {
            name: {
                node.target.id: source.annotation(node.annotation)
                for node in ast.walk(function)
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
            }
            for name, function in source.functions.items()
        }
        self.requirements = requirements
        self.safety = []
        self.domains = []
        self.stack = []
        self.summaries = frozenset(summaries)
        self.assumptions = []
        self.quantifier_depth = 0
        self.loop_obligations = []
        self.loop_replays = []
        self.loop_nodes = {}
        self.sums = {}
        self.return_paths = {}
        self.memo = {}
        self.nonnegative = set()
        self.aggregates = {}
        self.input_integers = set()
        self.residues = {}
        self.known_types = set()
        self.expression_roots = {}
        for declaration in requirements.get('loops', []):
            function = source.functions[declaration['function']]
            for node in ast.walk(function):
                if isinstance(node, ast.For) and ast.unparse(node.target) == declaration['target'] and ast.dump(node.iter) == ast.dump(source.expression(declaration['iter'])):
                    self.loop_nodes[id(node)] = declaration

    def sort(self, typ):
        if typ.kind == 'literal':
            typ = Type({int: 'int', bool: 'bool', str: 'str'}[type(typ.args[0])])
        sorts = {'int': z3.IntSort(), 'bool': z3.BoolSort(), 'str': TEXT,
                 'union': IDENTITY, 'optional': OPTIONAL_TEXT}
        if typ.kind not in sorts:
            raise VerificationError('Sequence elements require a scalar type')
        return sorts[typ.kind]

    def typed(self, value, typ):
        key = (self.value_key(value), typ)
        if key in self.known_types:
            return z3.BoolVal(True)
        if typ.kind == "int":
            return z3.BoolVal(type(value) is int or z3.is_int(value))
        if typ.kind == "bool":
            return z3.BoolVal(type(value) is bool or z3.is_bool(value))
        if typ.kind == 'str':
            if type(value) is str:
                return z3.BoolVal(True)
            if isinstance(value, Label):
                return z3.BoolVal(True)
            if not is_text(value):
                return z3.BoolVal(False)
            if z3.is_app(value) and value.decl().kind() == z3.Z3_OP_ITE:
                return z3.And(z3.Implies(value.arg(0), self.typed(value.arg(1), typ)), z3.Implies(z3.Not(value.arg(0)), self.typed(value.arg(2), typ)))
            value = text_value(value)
            i = z3.FreshInt('codepoint')
            return z3.ForAll(i, z3.Implies(z3.And(0 <= i, i < z3.Length(value)), z3.And(0 <= value[i], value[i] <= 0x10ffff)))
        if typ.kind == 'optional':
            if value is None or type(value) is str or isinstance(value, Label):
                return z3.BoolVal(True)
            if not is_optional_text(value):
                if is_text(value):
                    return self.typed(value, Type('str'))
                return z3.BoolVal(False)
            if z3.is_app(value) and value.decl().kind() == z3.Z3_OP_ITE:
                return z3.And(z3.Implies(value.arg(0), self.typed(value.arg(1), typ)), z3.Implies(z3.Not(value.arg(0)), self.typed(value.arg(2), typ)))
            return z3.Implies(OPTIONAL_TEXT.is_optional_some(value),
                              self.typed(OPTIONAL_TEXT.optional_value(value), Type('str')))
        if typ.kind == 'union':
            if isinstance(value, Label):
                return z3.BoolVal(True)
            if is_identity(value):
                if z3.is_app(value) and value.decl().kind() == z3.Z3_OP_ITE:
                    return z3.And(z3.Implies(value.arg(0), self.typed(value.arg(1), typ)), z3.Implies(z3.Not(value.arg(0)), self.typed(value.arg(2), typ)))
                if z3.is_app(value) and value.decl() == IDENTITY.integer_identity:
                    return z3.BoolVal(True)
                if z3.is_app(value) and value.decl() == IDENTITY.text_identity:
                    return self.typed(value.arg(0), Type('str'))
                return z3.Implies(IDENTITY.is_text_identity(value), self.typed(IDENTITY.text_value(value), Type('str')))
            return z3.Or(self.typed(value, Type('int')), self.typed(value, Type('str')))
        if typ.kind == "literal":
            expected = type(typ.args[0])
            if isinstance(value, Label):
                if typ.args == value.alternatives:
                    return z3.BoolVal(True)
                return z3.Or(*(equal(value, item) for item in typ.args)) if expected is str else z3.BoolVal(False)
            valid = {int: type(value) is int or z3.is_int(value), bool: type(value) is bool or z3.is_bool(value), str: is_text(value)}[expected]
            if not valid:
                return z3.BoolVal(False)
            return z3.Or(*(equal(value, item) for item in typ.args))
        if typ.kind == 'sequence':
            if isinstance(value, tuple):
                return z3.And(*(self.typed(item, typ.args[0]) for item in value))
            if not isinstance(value, Sequence) or value.element != typ.args[0]:
                return z3.BoolVal(False)
            i = z3.FreshInt('element')
            return z3.And(value.length >= 0, z3.ForAll(i, z3.Implies(z3.And(0 <= i, i < value.length), self.typed(value.values[i], value.element))))
        if typ.kind == "tuple":
            if not isinstance(value, tuple) or len(value) != len(typ.args):
                return z3.BoolVal(False)
            return z3.And(*(self.typed(v, t) for v, t in zip(value, typ.args)))
        if typ.kind == "record":
            if not isinstance(value, Record) or value.name != typ.args[0]:
                return z3.BoolVal(False)
            return z3.And(*(self.typed(value.fields[k], t) for k, t in self.source.records[value.name].items()))
        raise VerificationError("Unknown type")

    def symbol(self, name, typ):
        if typ.kind == 'literal' and type(typ.args[0]) is str:
            return Label(z3.Const(name, label_sort(typ.args)[0]), typ.args)
        if typ.kind == "record":
            return Record(typ.args[0], {key: self.symbol(name + "." + key, field) for key, field in self.source.records[typ.args[0]].items()})
        if typ.kind == "tuple":
            return tuple(self.symbol(name + "." + str(i), field) for i, field in enumerate(typ.args))
        if typ.kind == 'sequence':
            value = Sequence(z3.Int(name + '.length'), z3.Array(name + '.items', z3.IntSort(), self.sort(typ.args[0])), typ.args[0])
            self.nonnegative.add(value.length.get_id())
            self.domains.append(self.typed(value, typ))
            self.known_types.add((self.value_key(value), typ))
            return value
        kind = typ.kind
        if kind == "literal":
            kind = {int: "int", bool: "bool", str: "str"}[type(typ.args[0])]
        value = z3.Const(name, {'int': z3.IntSort(), 'bool': z3.BoolSort(), 'str': TEXT,
                                'union': IDENTITY, 'optional': OPTIONAL_TEXT}[kind])
        if kind == 'int':
            self.input_integers.add(value.get_id())
            self.expression_roots[value.get_id()] = value
        if typ.kind in ("literal", 'str', 'union', 'optional'):
            self.domains.append(self.typed(value, typ))
            self.known_types.add((self.value_key(value), typ))
        return value

    def positive_modulo(self, left, right):
        # Share exact residue definitions for scalar inputs. This is SSA-style
        # abbreviation, not a contract assumption: each fresh value is equated
        # to the original expression. It keeps quantified cyclic invariants in
        # bounded residue coordinates instead of mixed unbounded quotients.
        def normalize(value):
            if value.eq(right):
                return z3.IntVal(0)
            if value.get_id() in self.input_integers:
                key = (value.get_id(), right.get_id())
                if key not in self.residues:
                    residue = z3.FreshInt('residue')
                    self.residues[key] = residue
                    self.assumptions.append(residue == value % right)
                    self.nonnegative.add(residue.get_id())
                    self.expression_roots[residue.get_id()] = residue
                return self.residues[key]
            if z3.is_app(value):
                kind = value.decl().kind()
                if kind == z3.Z3_OP_MOD and value.arg(1).eq(right):
                    return normalize(value.arg(0))
                if kind in (z3.Z3_OP_ADD, z3.Z3_OP_SUB, z3.Z3_OP_MUL, z3.Z3_OP_UMINUS):
                    return value.decl()(*(normalize(child) for child in value.children()))
            return value
        normalized = z3.simplify(normalize(left))
        if any(normalized.eq(residue) and modulus == right.get_id() for (_, modulus), residue in self.residues.items()):
            return normalized
        return modulo(normalized, right)

    def length(self, value):
        if isinstance(value, tuple):
            return z3.IntVal(len(value))
        if isinstance(value, (Sequence, Range)):
            return value.length
        raise VerificationError('len requires a tuple')

    def sequence_scalar(self, value, typ):
        if isinstance(value, Label):
            if typ.kind == 'literal':
                return value.value
            if typ.kind == 'union':
                return identity_value(value)
            value = label_text(value)
        if typ.kind == 'union':
            return identity_value(value)
        if typ.kind == 'str':
            return text_value(value)
        if typ.kind == 'optional':
            return optional_text_value(value)
        if typ.kind == 'int':
            return integer(value)
        if typ.kind == 'bool':
            return boolean(value)
        if typ.kind == 'literal':
            return value
        raise VerificationError('Sequence concatenation requires scalar elements')

    def concatenate_sequence(self, left, right, guard):
        if not right:
            return left
        for item in right:
            self.require(self.typed(item, left.element), guard, 'sequence concatenation element type')
        total = left.length + len(right)
        index = z3.FreshInt('concat.index')
        tail_guard = z3.And(guard, index >= left.length, index < total)
        tail = self.index(right, index - left.length, tail_guard)
        body = z3.If(index < left.length, left.values[index], self.sequence_scalar(tail, left.element))
        return Sequence(total, z3.Lambda(index, body), left.element)

    def index(self, value, index, guard):
        index = integer(index)
        length = self.length(value)
        self.require(z3.And(-length <= index, index < length), guard, 'tuple index bounds')
        if index.get_id() in self.nonnegative or z3.is_int_value(index) and index.as_long() >= 0:
            self.require(index >= 0, guard, 'nonnegative index normalization')
            normalized = index
        else:
            normalized = z3.If(index < 0, index + length, index)
        if isinstance(value, Sequence):
            return value.values[normalized]
        if not value:
            # A loop over a statically empty tuple still has a symbolic body
            # during contract construction. Its loop guard is unsatisfiable;
            # retain that safety obligation and provide an unreachable value.
            self.require(z3.BoolVal(False), guard, 'empty fixed tuple index')
            return z3.IntVal(0)
        result = value[-1]
        for i in reversed(range(len(value) - 1)):
            result = choose(normalized == i, value[i], result)
        return result

    def require(self, condition, guard, reason):
        self.safety.append((reason, z3.Implies(z3.And(*self.assumptions, boolean(guard)), boolean(condition))))

    def expression(self, text, env, guard=True):
        return self.expr(self.source.expression(text), env, boolean(guard))

    def aggregate(self, node, env, guard):
        if len(node.args) != 4 or node.keywords or not isinstance(node.args[0], ast.Name):
            raise VerificationError('Bounded aggregation requires (binder, lower, upper, body)')
        name = node.args[0].id
        if name in env or name in self.source.functions or name in self.source.records or name in self.source.constants:
            raise VerificationError('Bounded binder shadows an existing name')
        lower, upper = (integer(self.expr(x, env, guard)) for x in node.args[1:3])
        index = z3.FreshInt('bound')
        if z3.is_int_value(lower) and lower.as_long() >= 0:
            self.nonnegative.add(index.get_id())
            self.expression_roots[index.get_id()] = index
        within = z3.And(lower <= index, index < upper)
        start = len(self.safety)
        assumptions_start = len(self.assumptions)
        self.quantifier_depth += 1
        try:
            value = self.expr(node.args[3], env | {name: index}, z3.And(guard, within))
        finally:
            self.quantifier_depth -= 1
        safety = self.safety[start:]
        del self.safety[start:]
        self.safety.extend((reason, z3.ForAll(index, condition)) for reason, condition in safety)
        from z3.z3util import get_vars
        escaped = [assumption for assumption in self.assumptions[assumptions_start:]
                   if any(variable.eq(index) for variable in get_vars(assumption))]
        if escaped:
            del self.assumptions[assumptions_start:]
            raise VerificationError(
                'Binder-dependent assumptions cannot escape range aggregation'
            )
        if node.func.id in ('forall_range', 'exists_range'):
            value = boolean(value)
            canonical = z3.Int('$quantifier.bound')
            term = z3.substitute(value, (index, canonical))
            key = (node.func.id, lower.sexpr(), term.sexpr())
            known = self.aggregates.setdefault(key, [])
            is_all = node.func.id == 'forall_range'
            for previous_upper, previous in known:
                difference = z3.simplify(upper - previous_upper)
                if z3.is_int_value(difference) and difference.as_long() == 0:
                    return previous
                if z3.is_int_value(difference) and difference.as_long() == 1:
                    last = z3.substitute(value, (index, previous_upper))
                    combined = z3.And(previous, last) if is_all else z3.Or(previous, last)
                    result = z3.If(previous_upper >= lower, combined, z3.BoolVal(is_all))
                    known.append((upper, result))
                    return result
            result = z3.ForAll(index, z3.Implies(within, value)) if is_all else z3.Exists(index, z3.And(within, value))
            known.append((upper, result))
            return result
        value = integer(value)
        # A mathematical finite sum is defined recursively, not postulated as a
        # summary of any source helper. Recursion decreases pos-lower until zero.
        canonical = z3.Int('$sum.bound')
        term = z3.substitute(value, (index, canonical))
        key = (lower.sexpr(), term.sexpr())
        if key not in self.sums:
            from z3.z3util import get_vars
            variables = []
            for variable in get_vars(lower) + get_vars(term):
                if not variable.eq(canonical) and not any(variable.eq(old) for old in variables):
                    variables.append(variable)
            position = z3.FreshInt('sum.position')
            function = z3.RecFunction(str(z3.FreshInt('finite.sum')), *(v.sort() for v in variables), z3.IntSort(), z3.IntSort())
            body = z3.If(position <= lower, 0, function(*variables, position - 1) + z3.substitute(term, (canonical, position - 1)))
            z3.RecAddDefinition(function, (*variables, position), body)
            self.sums[key] = (function, variables)
        function, variables = self.sums[key]
        return function(*variables, upper)

    def expr(self, node, env, guard):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if self.stack and node.id in self.source.locals[self.stack[-1]]:
                raise VerificationError("Unbound local name: " + node.id)
            if node.id in self.source.constants:
                return self.source.constants[node.id]
            raise VerificationError("Unbound name: " + node.id)
        if isinstance(node, ast.Attribute):
            value = self.expr(node.value, env, guard)
            if not isinstance(value, Record) or node.attr not in value.fields:
                raise VerificationError("Unknown record attribute: " + node.attr)
            return value.fields[node.attr]
        if isinstance(node, ast.Tuple):
            return tuple(self.expr(x, env, guard) for x in node.elts)
        if isinstance(node, ast.Subscript):
            value = self.expr(node.value, env, guard)
            if isinstance(value, tuple) and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int:
                if not -len(value) <= node.slice.value < len(value):
                    raise VerificationError('Invalid fixed tuple index')
                return value[node.slice.value]
            return self.index(value, self.expr(node.slice, env, guard), guard)
        if isinstance(node, ast.UnaryOp):
            value = self.expr(node.operand, env, guard)
            if isinstance(node.op, ast.Not):
                return z3.Not(boolean(value))
            return -integer(value) if isinstance(node.op, ast.USub) else integer(value)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Add):
                left_value = self.expr(node.left, env, guard)
                right_value = self.expr(node.right, env, guard)
                if isinstance(left_value, Sequence) and isinstance(right_value, tuple):
                    return self.concatenate_sequence(left_value, right_value, guard)
                if isinstance(left_value, tuple) and isinstance(right_value, tuple):
                    return left_value + right_value
                left, right = integer(left_value), integer(right_value)
                return left + right
            left, right = integer(self.expr(node.left, env, guard)), integer(self.expr(node.right, env, guard))
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            self.require(right != 0, guard, "division by zero")
            # Z3's negative-divisor division differs from Python's floor division.
            quotient = z3.If(right > 0, left / right, (-left) / (-right))
            if isinstance(node.op, ast.FloorDiv):
                return quotient
            if right.get_id() in self.nonnegative or z3.is_int_value(right) and right.as_long() > 0:
                self.require(right > 0, guard, 'positive modulo normalization')
                result = self.positive_modulo(left, right)
                self.nonnegative.add(result.get_id())
                self.expression_roots[result.get_id()] = result
                return result
            return z3.If(right > 0, modulo(left, right), -modulo(-left, -right))
        if isinstance(node, ast.BoolOp):
            result = boolean(self.expr(node.values[0], env, guard))
            for item in node.values[1:]:
                active = result if isinstance(node.op, ast.And) else z3.Not(result)
                value = boolean(self.expr(item, env, z3.And(guard, active)))
                result = z3.And(result, value) if isinstance(node.op, ast.And) else z3.Or(result, value)
            return result
        if isinstance(node, ast.Compare):
            left = self.expr(node.left, env, guard)
            result = z3.BoolVal(True)
            for op, rhs in zip(node.ops, node.comparators):
                right = self.expr(rhs, env, z3.And(guard, result))
                if isinstance(op, (ast.In, ast.NotIn)):
                    if isinstance(right, tuple):
                        comparison = z3.Or(*(equal(left, value) for value in right))
                    elif isinstance(right, Sequence):
                        i = z3.FreshInt('membership')
                        comparison = z3.Exists(i, z3.And(0 <= i, i < right.length, equal(left, right.values[i])))
                    else:
                        raise VerificationError('Membership requires a tuple')
                    if isinstance(op, ast.NotIn):
                        comparison = z3.Not(comparison)
                elif isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
                    comparison = equal(left, right)
                    if isinstance(op, (ast.NotEq, ast.IsNot)):
                        comparison = z3.Not(comparison)
                else:
                    a, b = integer(left), integer(right)
                    comparison = {ast.Lt: lambda: a < b, ast.LtE: lambda: a <= b, ast.Gt: lambda: a > b, ast.GtE: lambda: a >= b}[type(op)]()
                result = z3.And(result, comparison)
                left = right
            return result
        if isinstance(node, ast.IfExp):
            cond = boolean(self.expr(node.test, env, guard))
            return choose(cond, self.expr(node.body, env, z3.And(guard, cond)), self.expr(node.orelse, env, z3.And(guard, z3.Not(cond))))
        if isinstance(node, ast.Call):
            name = node.func.id
            if name in ('forall_range', 'exists_range', 'sum_range'):
                return self.aggregate(node, env, guard)
            args = [self.expr(x, env, guard) for x in node.args]
            kwargs = {x.arg: self.expr(x.value, env, guard) for x in node.keywords}
            if name in ('len', 'range'):
                if len(args) != 1 or kwargs:
                    raise VerificationError(name + ' requires one argument')
                if name == 'len':
                    return self.length(args[0])
                count = integer(args[0])
                nonnegative = count.get_id() in self.nonnegative or z3.is_int_value(count) and count.as_long() >= 0
                return Range(count if nonnegative else z3.If(count > 0, count, 0))
            if name == "replace":
                if len(args) != 1 or not isinstance(args[0], Record):
                    raise VerificationError("replace requires one immutable record")
                value = args[0]
                if set(kwargs) - set(value.fields):
                    raise VerificationError("Unknown replace fields")
                result = Record(value.name, {**value.fields, **kwargs})
                self.require(self.typed(result, Type("record", (value.name,))), guard, "replace field types")
                return result
            if name in self.source.records:
                fields = self.bind_arguments(name, self.source.records[name], args, kwargs, self.source.defaults[name], guard)
                result = Record(name, fields)
                self.require(self.typed(result, Type("record", (name,))), guard, "constructor field types")
                return result
            return self.call(name, args, kwargs, guard)
        raise VerificationError("Unsupported expression: " + type(node).__name__)

    def bind_arguments(self, name, parameters, args, kwargs, defaults, guard):
        keys = list(parameters)
        if len(args) > len(keys) or set(kwargs) - set(keys) or set(keys[:len(args)]) & set(kwargs):
            raise VerificationError("Invalid arguments to " + name)
        env = dict(zip(keys, args)) | kwargs
        for key in keys:
            if key not in env:
                if key not in defaults:
                    raise VerificationError("Missing argument " + key + " to " + name)
                env[key] = self.expr(defaults[key], self.source.constants, guard)
        return env

    def value_key(self, value):
        if isinstance(value, Record):
            return ('record', value.name, tuple((key, self.value_key(item)) for key, item in value.fields.items()))
        if isinstance(value, Label):
            return ('label', value.alternatives, value.value)
        if isinstance(value, Sequence):
            return ('sequence', value.element, value.length, value.values)
        if isinstance(value, tuple):
            return ('tuple', tuple(self.value_key(item) for item in value))
        if isinstance(value, z3.ExprRef):
            return ('expression', value)
        return (type(value), value)

    def call(self, name, args, kwargs, guard=True, check_preconditions=True):
        if z3.is_false(z3.simplify(boolean(guard))):
            return self.symbol(str(z3.FreshInt('unreachable.' + name)), self.source.signatures[name][1])
        if self.quantifier_depth and self._has_transitive_loop(name):
            raise VerificationError(
                'Looping helper calls are unsupported under range aggregation: ' + name
            )
        summarize = name in self.summaries and self.quantifier_depth == 0
        if self.assumptions or summarize or any(isinstance(node, ast.For) for node in ast.walk(self.source.functions[name])):
            return self._call(name, args, kwargs, guard, check_preconditions)
        guard = z3.simplify(boolean(guard))
        key = (name, self.value_key(tuple(args)), tuple((k, self.value_key(v)) for k, v in kwargs.items()), guard, check_preconditions)
        if key in self.memo:
            result, safety, domains = self.memo[key]
            self.safety.extend(safety)
            self.domains.extend(domains)
            return result
        safety_start, domains_start, loops_start = len(self.safety), len(self.domains), len(self.loop_obligations)
        result = self._call(name, args, kwargs, guard, check_preconditions)
        if not self.assumptions and loops_start == len(self.loop_obligations):
            self.memo[key] = (result, self.safety[safety_start:], self.domains[domains_start:])
        return result

    def _has_transitive_loop(self, name, seen=None):
        """Whether a helper or anything it specifies contains an inductive loop."""
        seen = set() if seen is None else seen
        if name in seen:
            return False
        seen.add(name)
        function = self.source.functions[name]
        if any(isinstance(node, ast.For) for node in ast.walk(function)):
            return True
        expressions = self.requirements.get('contracts', {}).get(name, {})
        trees = [function]
        trees.extend(self.source.expression(value)
                     for key in ('requires', 'ensures')
                     for value in expressions.get(key, ()))
        for tree in trees:
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in self.source.functions
                        and self._has_transitive_loop(node.func.id, seen)):
                    return True
        return False

    def _call(self, name, args, kwargs, guard=True, check_preconditions=True):
        if name in self.stack:
            raise VerificationError("Recursive calls through requirements are unsupported")
        self.stack.append(name)
        try:
            fn = self.source.functions[name]
            parameters, returns = self.source.signatures[name]
            defaults = dict(zip(list(parameters)[len(parameters) - len(fn.args.defaults):], fn.args.defaults))
            env = self.bind_arguments(name, parameters, args, kwargs, defaults, guard)
            for key, typ in parameters.items():
                self.require(self.typed(env[key], typ), guard, name + " argument " + key)
            if check_preconditions:
                active = guard
                for expression in self.requirements.get("contracts", {}).get(name, {}).get("requires", []):
                    condition = self.expression(expression, env, active)
                    self.require(condition, active, name + " precondition")
                    active = z3.And(active, boolean(condition))
            if (name in self.summaries and len(self.stack) > 1
                    and self.quantifier_depth == 0):
                result = self.symbol(str(z3.FreshInt('result.' + name)), returns)
                for expression in self.requirements.get('contracts', {}).get(name, {}).get('ensures', []):
                    self.assumptions.append(z3.Implies(boolean(guard), boolean(self.expression(expression, env | {'result': result}, guard))))
                return result
            active, paths = self.execute(fn.body, [(boolean(guard), env)])
            for path, _ in active:
                self.require(False, path, name + ' return coverage')
            if not paths:
                raise VerificationError("Function has no return: " + name)
            # Loop exits are an overapproximation justified by the separate
            # induction/termination VCs, not a fixed number of unrolled steps.
            if any(isinstance(node, ast.For) for node in ast.walk(fn)):
                self.assumptions.append(z3.Implies(boolean(guard), z3.Or(*(path for path, _ in paths))))
            else:
                self.require(z3.Or(*(path for path, _ in paths)), guard, name + " return coverage")
            for path, result in paths:
                self.require(self.typed(result, returns), path, name + " return type")
            self.return_paths[name] = paths
            result = paths[-1][1]
            for path, value in reversed(paths[:-1]):
                result = choose(path, value, result)
            return result
        finally:
            self.stack.pop()

    def execute(self, statements, active):
        returned = []
        for node in statements:
            next_active = []
            for guard, original in active:
                guard = z3.simplify(guard)
                if z3.is_false(guard):
                    continue
                env = dict(original)
                if isinstance(node, ast.Return):
                    returned.append((guard, self.expr(node.value, env, guard)))
                elif isinstance(node, ast.Raise):
                    self.require(False, guard, 'exception: ' + node.exc.args[0].value)
                elif isinstance(node, ast.Pass) or docstring(node):
                    next_active.append((guard, env))
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = self.expr(node.value, env, guard)
                    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    if isinstance(target, ast.Name):
                        env[target.id] = value
                    else:
                        if not isinstance(value, tuple) or len(value) != len(target.elts):
                            raise VerificationError("Tuple unpacking arity mismatch")
                        env.update({n.id: v for n, v in zip(target.elts, value)})
                    if isinstance(node, ast.AnnAssign):
                        self.require(self.typed(value, self.source.annotation(node.annotation)), guard, "local annotation")
                    elif isinstance(target, ast.Name) and target.id in self.local_types.get(self.stack[-1], {}):
                        self.require(self.typed(value, self.local_types[self.stack[-1]][target.id]), guard, "local assignment type")
                    next_active.append((guard, env))
                elif isinstance(node, ast.If):
                    cond = z3.simplify(boolean(self.expr(node.test, env, guard)))
                    for branch, selected in ((node.body, cond), (node.orelse, z3.Not(cond))):
                        if z3.is_false(z3.simplify(selected)):
                            continue
                        ongoing, exits = self.execute(branch, [(z3.And(guard, selected), env)])
                        next_active.extend(ongoing)
                        returned.extend(exits)
                elif isinstance(node, ast.For):
                    ongoing, exits = self.loop(node, guard, env)
                    next_active.extend(ongoing)
                    returned.extend(exits)
                else:
                    raise VerificationError("Unsupported statement")
            active = next_active
        return active, returned

    def statements(self, statements, active, returned):
        _, exits = self.execute(statements, active)
        returned.extend(exits)
        return returned

    def fresh_like(self, name, value, typ=None):
        if isinstance(value, Label):
            return Label(z3.FreshConst(value.value.sort(), name), value.alternatives)
        if isinstance(value, Record):
            fields = self.source.records[value.name]
            return Record(value.name, {
                key: self.fresh_like(name + '.' + key, item, fields[key])
                for key, item in value.fields.items()
            })
        if isinstance(value, tuple):
            element_types = typ.args if typ is not None and typ.kind == 'tuple' else (None,) * len(value)
            return tuple(self.fresh_like(name + '.' + str(index), item, element_types[index])
                         for index, item in enumerate(value))
        if isinstance(value, Sequence):
            return self.symbol(str(z3.FreshInt(name)), Type('sequence', (value.element,)))
        if typ is not None and typ.kind in ('optional', 'str', 'literal', 'union', 'int', 'bool'):
            fresh = z3.FreshConst(self.sort(typ), name)
            self.domains.append(self.typed(fresh, typ))
            return fresh
        if value is None:
            raise VerificationError('Loop-local None requires an explicit supported annotation')
        if is_optional_text(value):
            fresh = z3.FreshConst(OPTIONAL_TEXT, name)
            self.domains.append(self.typed(fresh, Type('optional', (Type('str'),))))
            return fresh
        if type(value) is bool:
            value = z3.BoolVal(value)
        elif type(value) is int:
            value = z3.IntVal(value)
        elif type(value) is str:
            value = text_value(value)
        if not isinstance(value, z3.ExprRef):
            raise VerificationError('Unsupported loop-local type')
        fresh = z3.FreshConst(value.sort(), name)
        if is_text(value):
            self.domains.append(self.typed(fresh, Type('str')))
        return fresh

    def loop(self, node, guard, env):
        declaration = self.loop_nodes.get(id(node))
        if declaration is None:
            raise VerificationError('Every source loop needs an exact .inv loop declaration')
        iterable = self.expr(node.iter, env, guard)
        if not isinstance(iterable, (tuple, Sequence, Range)):
            raise VerificationError('Loop iterable must be an immutable tuple or range(n)')
        count = self.length(iterable)
        cursor = declaration['cursor']
        if cursor in self.source.locals[self.stack[-1]] or cursor in self.source.constants or cursor in self.source.functions:
            raise VerificationError('Loop cursor shadows a source name')
        writes = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        # Iterating a snapshot and mutating only scalar/local bindings preserves
        # the iterable. Reject reassignment of an input used by its expression.
        read_iterable = {n.id for n in ast.walk(node.iter) if isinstance(n, ast.Name)}
        if writes & read_iterable:
            raise VerificationError('Loop body must not rebind its iterable')
        prefix = self.stack[-1] + '.' + declaration['name']
        inherited = list(self.assumptions)

        def obligation(name, condition, replay=None):
            self.loop_obligations.append((prefix + '.' + name, z3.Implies(z3.And(*inherited), condition)))
            self.loop_replays.append(replay)

        def invariant(local):
            result = z3.And(0 <= local[cursor], local[cursor] <= count)
            for expression in declaration['invariants']:
                result = z3.And(result, boolean(self.expression(expression, local, z3.And(guard, result))))
            return result

        base = env | {cursor: z3.IntVal(0)}
        obligation('init', z3.Implies(guard, invariant(base)))
        local_types = self.local_types.get(self.stack[-1], {})
        head = {key: self.fresh_like(prefix + '.' + key, value, local_types.get(key)) if key in writes else value for key, value in env.items()}
        k = z3.FreshInt(prefix + '.cursor')
        head[cursor] = k
        inv = invariant(head)
        obligation('bounds', z3.Implies(z3.And(guard, inv), z3.And(0 <= k, k <= count)))
        variant = integer(self.expression(declaration['decreases'], head, z3.And(guard, inv)))
        obligation('nonnegative', z3.Implies(z3.And(guard, inv), variant >= 0))
        body_guard = z3.And(guard, inv, k < count)
        cursor_remainder = k % count == k
        obligation('cursor_remainder', z3.Implies(body_guard, cursor_remainder))
        body_guard = z3.And(body_guard, cursor_remainder)
        body_env = head | {node.target.id: k if isinstance(iterable, Range) else self.index(iterable, k, body_guard)}
        ongoing, returned = self.execute(node.body, [(body_guard, body_env)])
        for number, (path, local) in enumerate(ongoing):
            after = local | {cursor: k + 1}
            obligation('preserve.' + str(number), z3.Implies(path, invariant(after)), {
                'function': self.stack[-1],
                'arguments': {key: head[key] for key in self.source.signatures[self.stack[-1]][0]},
            })
            next_variant = integer(self.expression(declaration['decreases'], after, path))
            obligation('decrease.' + str(number), z3.Implies(path, z3.And(next_variant >= 0, next_variant < variant)))
        # Arbitrary invariant-preserving exit values cover every terminating
        # execution; termination follows from the checked integer variant.
        exited = {key: self.fresh_like(prefix + '.exit.' + key, value, local_types.get(key)) if key in writes else value for key, value in env.items()}
        exited[cursor] = count
        exit_guard = z3.And(guard, invariant(exited))
        exited.pop(cursor)
        return [(exit_guard, exited)], returned
