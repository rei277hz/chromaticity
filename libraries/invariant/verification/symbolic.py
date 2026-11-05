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
OPTIONALS = {}
for _kind, _sort in (('str', TEXT), ('int', z3.IntSort()), ('bool', z3.BoolSort())):
    _optional = z3.Datatype('InvariantOptional_' + _kind)
    _optional.declare('optional_none_' + _kind)
    _optional.declare('optional_some_' + _kind, ('optional_value_' + _kind, _sort))
    _created = _optional.create()
    # Distinct SMT names keep mixed-Optional obligations independently parsable.
    _created.optional_none = _created.constructor(0)()
    _created.optional_some = _created.constructor(1)
    _created.optional_value = _created.accessor(1, 0)
    _created.is_optional_none = _created.recognizer(0)
    _created.is_optional_some = _created.recognizer(1)
    OPTIONALS[_kind] = _created
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


def optional_type(value):
    if isinstance(value, z3.ExprRef):
        for kind, sort in OPTIONALS.items():
            if value.sort() == sort:
                return Type(kind)
    return None


def scalar_type(value):
    optional = optional_type(value)
    if optional is not None:
        return optional
    if isinstance(value, Label) or is_text(value):
        return Type('str')
    if type(value) is bool or z3.is_bool(value):
        return Type('bool')
    if type(value) is int or z3.is_int(value):
        return Type('int')
    raise VerificationError('Optional requires a supported scalar')


def optional_value(value, element):
    sort = OPTIONALS[element.kind]
    if value is None:
        return sort.optional_none
    if optional_type(value) == element:
        return value
    if isinstance(value, Label):
        value = label_text(value)
    if optional_type(value) is None and scalar_type(value) == element:
        return sort.optional_some(text_value(value) if element.kind == 'str' else value)
    raise VerificationError('Optional[' + element.kind + '] requires its scalar type or None')


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
    codec: object = None
    typing: object = None

    def at(self, index):
        value = self.values[index]
        return self.codec.unpack(value, self.element) if self.codec is not None else value


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

    Removing inner reductions is exact in integer modular arithmetic. Bounded
    residue sums/differences have linear results; expose those cases while
    retaining the exact reduction everywhere else. Division and all other
    operations are deliberately opaque to this rewrite.
    """
    def lift(value):
        if z3.is_app(value):
            kind = value.decl().kind()
            if kind == z3.Z3_OP_MOD and value.arg(1).eq(right):
                return lift(value.arg(0))
            if kind in (z3.Z3_OP_ADD, z3.Z3_OP_SUB, z3.Z3_OP_MUL, z3.Z3_OP_UMINUS):
                return value.decl()(*(lift(child) for child in value.children()))
        return value
    reduced = z3.simplify(lift(left) % right)
    if z3.is_app(reduced) and reduced.decl().kind() == z3.Z3_OP_MOD:
        dividend, divisor = reduced.arg(0), reduced.arg(1)
        # Each guard implies a positive divisor. Negative and zero divisors,
        # and all unbounded operands, retain their original Z3 expression.
        return z3.If(z3.And(0 <= dividend, dividend < divisor), dividend,
                     z3.If(z3.And(-divisor <= dividend, dividend < 0), dividend + divisor,
                           z3.If(z3.And(divisor <= dividend, dividend < 2 * divisor),
                                 dividend - divisor, reduced)))
    return reduced


def equal(left, right):
    if isinstance(left, Label) or isinstance(right, Label):
        if isinstance(left, Label) and isinstance(right, Label) and left.alternatives == right.alternatives:
            return left.value == right.value
        if isinstance(left, Label) and type(right) is str:
            return left.value == label_sort(left.alternatives)[1][left.alternatives.index(right)] if right in left.alternatives else z3.BoolVal(False)
        if isinstance(right, Label) and type(left) is str:
            return equal(right, left)
        return equal(label_text(left) if isinstance(left, Label) else left, label_text(right) if isinstance(right, Label) else right)
    left_optional, right_optional = optional_type(left), optional_type(right)
    if left is None or right is None:
        if left is None and right is None:
            return z3.BoolVal(True)
        other, element = (right, right_optional) if left is None else (left, left_optional)
        return OPTIONALS[element.kind].is_optional_none(other) if element is not None else z3.BoolVal(False)
    if left_optional is not None or right_optional is not None:
        if left_optional is not None and right_optional is not None:
            a, b = OPTIONALS[left_optional.kind], OPTIONALS[right_optional.kind]
            return z3.Or(z3.And(a.is_optional_none(left), b.is_optional_none(right)),
                         z3.And(a.is_optional_some(left), b.is_optional_some(right),
                                equal(a.optional_value(left), b.optional_value(right))))
        value, other, element = (left, right, left_optional) if left_optional is not None else (right, left, right_optional)
        sort = OPTIONALS[element.kind]
        return z3.And(sort.is_optional_some(value), equal(sort.optional_value(value), other))
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
            return z3.And(sequence.length == len(other), *(equal(sequence.at(index), item) for index, item in enumerate(other)))
        if not isinstance(left, Sequence) or not isinstance(right, Sequence):
            return z3.BoolVal(False)
        same_length = left.length == right.length
        if left.element == right.element and left.values.eq(right.values):
            return same_length
        i = z3.FreshInt('equality.index')
        members = z3.ForAll(i, z3.Implies(z3.And(0 <= i, i < left.length), equal(left.at(i), right.at(i))))
        if left.element == right.element and left.values.sort() == right.values.sort():
            # Equal storage is sufficient, but Python tuple equality ignores
            # entries beyond the represented length. Keep that semantic case.
            members = z3.Or(left.values == right.values, members)
        return z3.And(same_length, members)
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
    optional = False
    for value in values:
        if value is None:
            optional = True
        elif optional_type(value) is not None:
            optional = True
            kinds.add(optional_type(value).kind)
        elif isinstance(value, Label):
            kinds.add('str')
        elif is_identity(value):
            kinds.add('union')
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
    if optional:
        return Type('optional', (Type(next(iter(kinds))),)) if len(kinds) == 1 and 'union' not in kinds else None
    if 'union' in kinds or {'int', 'str'} <= kinds:
        return Type('union', (Type('int'), Type('str')))
    return Type(next(iter(kinds))) if len(kinds) == 1 else None


def empty_sequence(element):
    if element.kind == 'union':
        default = identity_value(0)
    elif element.kind == 'optional':
        default = OPTIONALS[element.args[0].kind].optional_none
    elif element.kind == 'str':
        default = text_value('')
    elif element.kind == 'bool':
        default = z3.BoolVal(False)
    else:
        default = z3.IntVal(0)
    return Sequence(z3.IntVal(0), z3.K(z3.IntSort(), default), element, typing=z3.BoolVal(True))


def choose(condition, yes, no, context=None):
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
        return choose(condition, label_text(yes) if isinstance(yes, Label) else yes, label_text(no) if isinstance(no, Label) else no, context)
    if yes is None and no is None:
        return None
    if yes is None or no is None or optional_type(yes) is not None or optional_type(no) is not None:
        element = scalar_type(no if yes is None else yes)
        return z3.If(condition, optional_value(yes, element), optional_value(no, element))
    if (is_text(yes) and (type(no) is int or z3.is_int(no))) or (is_text(no) and (type(yes) is int or z3.is_int(yes))):
        return z3.If(condition, identity_value(yes), identity_value(no))
    if is_identity(yes) or is_identity(no):
        return z3.If(condition, identity_value(yes), identity_value(no))
    if is_text(yes) and is_text(no):
        return z3.If(condition, text_value(yes), text_value(no))
    if isinstance(yes, tuple) and isinstance(no, tuple) and len(yes) != len(no):
        if context is not None:
            element = context.tuple_element((*yes, *no))
            left, right = context.sequence(yes, element), context.sequence(no, element)
            return Sequence(z3.If(condition, left.length, right.length),
                            z3.If(condition, left.values, right.values), element, context,
                            z3.If(condition, context.typed(left, Type('sequence', (element,))),
                                  context.typed(right, Type('sequence', (element,)))))
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
            if sequence.codec is not None:
                return sequence.codec.sequence(value, sequence.element)
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
                    item = optional_value(item, sequence.element.args[0])
                values = z3.Store(values, index, item)
            return Sequence(z3.IntVal(len(value)), values, sequence.element)

        left, right = as_sequence(yes), as_sequence(no)
        codec = sequence.codec or context
        typing = (z3.If(condition, codec.typed(left, Type('sequence', (sequence.element,))),
                        codec.typed(right, Type('sequence', (sequence.element,))))
                  if codec is not None else None)
        return Sequence(z3.If(condition, left.length, right.length),
                        z3.If(condition, left.values, right.values),
                        sequence.element, codec, typing)
    if isinstance(yes, Sequence) and isinstance(no, Sequence) and yes.element == no.element:
        return Sequence(z3.If(condition, yes.length, no.length), z3.If(condition, yes.values, no.values), yes.element)
    if isinstance(yes, Record) and isinstance(no, Record) and yes.name == no.name:
        fields = {}
        for key in yes.fields:
            try:
                fields[key] = choose(condition, yes.fields[key], no.fields[key], context)
            except VerificationError as error:
                raise VerificationError(
                    f"Incompatible branch field {yes.name}.{key}: "
                    f"{type(yes.fields[key]).__name__} / {type(no.fields[key]).__name__}"
                ) from error
        return Record(yes.name, fields)
    if isinstance(yes, tuple) and isinstance(no, tuple) and len(yes) == len(no):
        return tuple(choose(condition, a, b, context) for a, b in zip(yes, no))
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
    def __init__(self, source, requirements):
        self.source = source
        self.storage_sorts = {}
        self.storage_identity = hashlib.sha256(repr(source.records).encode()).hexdigest()[:20]
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
        self.assumptions = []
        self.memo = {}
        self._reachability_cache = {}
        self._reachability_simplifier = z3.Then('simplify', 'ctx-simplify', 'simplify')
        self.nonnegative = set()
        self.input_integers = set()
        self.residues = {}
        self.known_types = set()
        self.expression_roots = {}

    def is_unreachable(self, original_guard):
        """Prune only a guard whose complete simplification is false.

        This is an optimization, not an assumption or a replacement for the
        original path condition. Inconclusive or interrupted simplification
        leaves the path available to the ordinary proof obligations.
        """
        guard = boolean(original_guard)
        identity = guard.get_id()
        cached = self._reachability_cache.get(identity)
        if cached is not None:
            return cached[1]
        unreachable = False
        try:
            simplified = z3.simplify(guard)
            if z3.is_false(simplified):
                unreachable = True
            elif not z3.is_true(simplified):
                result = self._reachability_simplifier(simplified)
                unreachable = z3.is_false(result.as_expr())
        except z3.Z3Exception:
            pass
        # Keep the AST alive so Z3 cannot reuse its identity for another guard.
        self._reachability_cache[identity] = (guard, unreachable)
        return unreachable

    def sort(self, typ):
        if typ.kind == 'literal':
            if type(typ.args[0]) is str:
                return label_sort(typ.args)[0]
            typ = Type({int: 'int', bool: 'bool', str: 'str'}[type(typ.args[0])])
        if typ.kind == 'optional':
            return OPTIONALS[typ.args[0].kind]
        sorts = {'int': z3.IntSort(), 'bool': z3.BoolSort(), 'str': TEXT,
                 'union': IDENTITY}
        if typ.kind in ('record', 'tuple', 'sequence'):
            if typ not in self.storage_sorts:
                name = 'InvariantValue_' + self.storage_identity + '_' + hashlib.sha256(repr(typ).encode()).hexdigest()[:20]
                data = z3.Datatype(name)
                if typ.kind == 'record':
                    fields = tuple(self.source.records[typ.args[0]].values())
                    members = tuple((name + '_field_' + str(i), self.sort(field)) for i, field in enumerate(fields))
                elif typ.kind == 'tuple':
                    members = tuple((name + '_field_' + str(i), self.sort(field)) for i, field in enumerate(typ.args))
                else:
                    members = ((name + '_length', z3.IntSort()), (name + '_items', z3.ArraySort(z3.IntSort(), self.sort(typ.args[0]))))
                data.declare(name + '_make', *members)
                self.storage_sorts[typ] = data.create()
            return self.storage_sorts[typ]
        if typ.kind not in sorts:
            raise VerificationError('Unsupported immutable sequence element type')
        return sorts[typ.kind]

    def pack(self, value, typ):
        """Encode immutable values in arrays without narrowing their domains."""
        if typ.kind == 'record':
            if not isinstance(value, Record) or value.name != typ.args[0]:
                raise VerificationError('Record sequence element type differs')
            fields = self.source.records[value.name]
            return self.sort(typ).constructor(0)(*(self.pack(value.fields[key], field) for key, field in fields.items()))
        if typ.kind == 'tuple':
            if not isinstance(value, tuple) or len(value) != len(typ.args):
                raise VerificationError('Fixed tuple sequence element type differs')
            return self.sort(typ).constructor(0)(*(self.pack(item, field) for item, field in zip(value, typ.args)))
        if typ.kind == 'sequence':
            sequence = self.sequence(value, typ.args[0])
            return self.sort(typ).constructor(0)(sequence.length, sequence.values)
        if typ.kind == 'literal':
            if type(typ.args[0]) is str:
                _, constructors = label_sort(typ.args)
                if isinstance(value, Label) and value.alternatives == typ.args:
                    return value.value
                result = constructors[-1]
                for alternative, constructor in reversed(list(zip(typ.args[:-1], constructors[:-1]))):
                    result = z3.If(equal(value, alternative), constructor, result)
                return result
            if isinstance(value, Label):
                value = label_text(value)
            typ = Type({int: 'int', bool: 'bool', str: 'str'}[type(typ.args[0])])
        return self.sequence_scalar(value, typ)

    def unpack(self, value, typ):
        if typ.kind == 'literal' and type(typ.args[0]) is str:
            return Label(value, typ.args)
        if typ.kind == 'record':
            sort = self.sort(typ)
            return Record(typ.args[0], {key: self.unpack(sort.accessor(0, i)(value), field)
                                      for i, (key, field) in enumerate(self.source.records[typ.args[0]].items())})
        if typ.kind == 'tuple':
            sort = self.sort(typ)
            return tuple(self.unpack(sort.accessor(0, i)(value), field) for i, field in enumerate(typ.args))
        if typ.kind == 'sequence':
            sort = self.sort(typ)
            return Sequence(sort.accessor(0, 0)(value), sort.accessor(0, 1)(value), typ.args[0], self)
        return value

    def tuple_element(self, values):
        scalar = fixed_tuple_element(values)
        if scalar is not None:
            return scalar
        if values and all(isinstance(value, Record) and value.name == values[0].name for value in values):
            return Type('record', (values[0].name,))
        if values and all(isinstance(value, tuple) and len(value) == len(values[0]) for value in values):
            return Type('tuple', tuple(self.tuple_element(tuple(value[i] for value in values)) for i in range(len(values[0]))))
        raise VerificationError('Cannot infer immutable sequence element type')

    def sequence(self, values, element):
        if isinstance(values, Sequence):
            if values.element != element:
                raise VerificationError('Sequence element types differ')
            return values
        if not isinstance(values, tuple):
            raise VerificationError('Immutable sequence requires tuple values')
        array = z3.K(z3.IntSort(), z3.FreshConst(self.sort(element), 'sequence.default'))
        for index, value in enumerate(values):
            array = z3.Store(array, index, self.pack(value, element))
        typing = z3.And(*(self.typed(value, element) for value in values))
        return Sequence(z3.IntVal(len(values)), array, element, self, typing)

    def typed(self, value, typ):
        key = (self.value_key(value), typ)
        if key in self.known_types:
            return z3.BoolVal(True)
        if typ.kind in ('int', 'bool', 'str') and optional_type(value) == typ:
            sort = OPTIONALS[typ.kind]
            return z3.And(sort.is_optional_some(value), self.typed(sort.optional_value(value), typ))
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
            value = z3.simplify(value)
            if z3.is_app(value) and value.decl().kind() == z3.Z3_OP_ITE:
                return z3.And(z3.Implies(value.arg(0), self.typed(value.arg(1), typ)), z3.Implies(z3.Not(value.arg(0)), self.typed(value.arg(2), typ)))
            if z3.is_app(value):
                kind = value.decl().kind()
                if kind == z3.Z3_OP_SEQ_EMPTY:
                    return z3.BoolVal(True)
                if kind == z3.Z3_OP_SEQ_UNIT:
                    return z3.And(0 <= value.arg(0), value.arg(0) <= 0x10ffff)
                if kind == z3.Z3_OP_SEQ_CONCAT:
                    return z3.And(*(self.typed(part, typ) for part in value.children()))
            value = text_value(value)
            i = z3.FreshInt('codepoint')
            return z3.ForAll(i, z3.Implies(z3.And(0 <= i, i < z3.Length(value)), z3.And(0 <= value[i], value[i] <= 0x10ffff)))
        if typ.kind == 'optional':
            if value is None:
                return z3.BoolVal(True)
            element = typ.args[0]
            actual = optional_type(value)
            if actual is None:
                return self.typed(value, element)
            if actual != element:
                return z3.BoolVal(False)
            sort = OPTIONALS[element.kind]
            if z3.is_app(value) and value.decl() == sort.constructor(0):
                return z3.BoolVal(True)
            if z3.is_app(value) and value.decl() == sort.constructor(1):
                return self.typed(value.arg(0), element)
            if z3.is_app(value) and value.decl().kind() == z3.Z3_OP_ITE:
                return z3.And(z3.Implies(value.arg(0), self.typed(value.arg(1), typ)), z3.Implies(z3.Not(value.arg(0)), self.typed(value.arg(2), typ)))
            return z3.Implies(sort.is_optional_some(value),
                              self.typed(sort.optional_value(value), element))
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
            if value.typing is not None:
                return z3.And(value.length >= 0, value.typing)
            i = z3.FreshInt('element')
            return z3.And(value.length >= 0, z3.ForAll(i, z3.Implies(z3.And(0 <= i, i < value.length), self.typed(value.at(i), value.element))))
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
            value = Sequence(z3.Int(name + '.length'), z3.Array(name + '.items', z3.IntSort(), self.sort(typ.args[0])), typ.args[0], self)
            self.nonnegative.add(value.length.get_id())
            self.domains.append(self.typed(value, typ))
            self.known_types.add((self.value_key(value), typ))
            return value
        kind = typ.kind
        if kind == "literal":
            kind = {int: "int", bool: "bool", str: "str"}[type(typ.args[0])]
        value = z3.Const(name, self.sort(typ))
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
        if isinstance(value, Sequence):
            return value.length
        raise VerificationError('len requires a tuple')

    def sequence_scalar(self, value, typ):
        if typ.kind in ('record', 'tuple', 'sequence', 'literal'):
            return self.pack(value, typ)
        if optional_type(value) == typ:
            value = OPTIONALS[typ.kind].optional_value(value)
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
            return optional_value(value, typ.args[0])
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
        typing = z3.And(self.typed(left, Type('sequence', (left.element,))),
                        *(self.typed(item, left.element) for item in right))
        return Sequence(total, z3.Lambda(index, body), left.element, left.codec, typing)

    def concatenate(self, left, right, guard):
        sequence = left if isinstance(left, Sequence) else right
        element = sequence.element
        for value in (left, right):
            self.require(self.typed(value, Type('sequence', (element,))), guard,
                         'sequence concatenation element type')
        left, right = self.sequence(left, element), self.sequence(right, element)
        index = z3.FreshInt('concat.index')
        body = z3.If(index < left.length, left.values[index], right.values[index - left.length])
        typing = z3.And(self.typed(left, Type('sequence', (element,))),
                        self.typed(right, Type('sequence', (element,))))
        return Sequence(left.length + right.length, z3.Lambda(index, body), element, self, typing)

    def index(self, value, index, guard):
        index = self.scalar(index, 'int', guard)
        length = self.length(value)
        self.require(z3.And(-length <= index, index < length), guard, 'tuple index bounds')
        if index.get_id() in self.nonnegative or z3.is_int_value(index) and index.as_long() >= 0:
            self.require(index >= 0, guard, 'nonnegative index normalization')
            normalized = index
        else:
            normalized = z3.If(index < 0, index + length, index)
        if isinstance(value, Sequence):
            return value.at(normalized)
        if not value:
            # An empty tuple index is valid only on an unreachable path.
            self.require(z3.BoolVal(False), guard, 'empty fixed tuple index')
            return z3.IntVal(0)
        result = value[-1]
        for i in reversed(range(len(value) - 1)):
            result = choose(normalized == i, value[i], result, self)
        return result

    def require(self, condition, guard, reason):
        self.safety.append((reason, z3.Implies(z3.And(*self.assumptions, boolean(guard)), boolean(condition))))

    def scalar(self, value, kind, guard):
        if value is None:
            self.require(z3.BoolVal(False), guard, 'optional scalar is present')
            value = {'int': 0, 'bool': False, 'str': ''}[kind]
        if optional_type(value) == Type(kind):
            sort = OPTIONALS[kind]
            self.require(sort.is_optional_some(value), guard, 'optional scalar is present')
            value = sort.optional_value(value)
        return {'int': integer, 'bool': boolean, 'str': text_value}[kind](value)

    def expression(self, text, env, guard=True):
        return self.expr(self.source.expression(text), env, boolean(guard))


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
                return z3.Not(self.scalar(value, 'bool', guard))
            return -self.scalar(value, 'int', guard) if isinstance(node.op, ast.USub) else self.scalar(value, 'int', guard)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Add):
                left_value = self.expr(node.left, env, guard)
                right_value = self.expr(node.right, env, guard)
                if isinstance(left_value, Sequence) and isinstance(right_value, tuple):
                    return self.concatenate_sequence(left_value, right_value, guard)
                if (isinstance(left_value, (tuple, Sequence))
                        and isinstance(right_value, Sequence)):
                    return self.concatenate(left_value, right_value, guard)
                if isinstance(left_value, tuple) and isinstance(right_value, tuple):
                    return left_value + right_value
                left, right = self.scalar(left_value, 'int', guard), self.scalar(right_value, 'int', guard)
                return left + right
            left, right = (self.scalar(self.expr(item, env, guard), 'int', guard) for item in (node.left, node.right))
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
            result = self.scalar(self.expr(node.values[0], env, guard), 'bool', guard)
            for item in node.values[1:]:
                active = result if isinstance(node.op, ast.And) else z3.Not(result)
                active_guard = z3.And(guard, active)
                if self.is_unreachable(active_guard):
                    break
                value = self.scalar(self.expr(item, env, active_guard), 'bool', active_guard)
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
                        comparison = z3.Exists(i, z3.And(0 <= i, i < right.length, equal(left, right.at(i))))
                    else:
                        raise VerificationError('Membership requires a tuple')
                    if isinstance(op, ast.NotIn):
                        comparison = z3.Not(comparison)
                elif isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
                    comparison = equal(left, right)
                    if isinstance(op, (ast.NotEq, ast.IsNot)):
                        comparison = z3.Not(comparison)
                else:
                    a, b = self.scalar(left, 'int', z3.And(guard, result)), self.scalar(right, 'int', z3.And(guard, result))
                    comparison = {ast.Lt: lambda: a < b, ast.LtE: lambda: a <= b, ast.Gt: lambda: a > b, ast.GtE: lambda: a >= b}[type(op)]()
                result = z3.And(result, comparison)
                left = right
            return result
        if isinstance(node, ast.IfExp):
            cond = self.scalar(self.expr(node.test, env, guard), 'bool', guard)
            yes_guard, no_guard = z3.And(guard, cond), z3.And(guard, z3.Not(cond))
            if self.is_unreachable(yes_guard):
                return self.expr(node.orelse, env, no_guard)
            if self.is_unreachable(no_guard):
                return self.expr(node.body, env, yes_guard)
            return choose(cond, self.expr(node.body, env, yes_guard), self.expr(node.orelse, env, no_guard), self)
        if isinstance(node, ast.Call):
            name = node.func.id
            args = [self.expr(x, env, guard) for x in node.args]
            kwargs = {x.arg: self.expr(x.value, env, guard) for x in node.keywords}
            if name == "len":
                if len(args) != 1 or kwargs:
                    raise VerificationError("len requires one argument")
                return self.length(args[0])
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
            typ = parameters[key]
            if typ.kind == 'sequence' and isinstance(env[key], tuple):
                self.require(self.typed(env[key], typ), guard, 'sequence argument type')
                env[key] = self.sequence(env[key], typ.args[0])
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
        guard = boolean(guard)
        if self.is_unreachable(guard):
            return self.symbol(str(z3.FreshInt('unreachable.' + name)), self.source.signatures[name][1])
        if self.assumptions:
            return self._call(name, args, kwargs, guard, check_preconditions)
        key = (name, self.value_key(tuple(args)), tuple((k, self.value_key(v)) for k, v in kwargs.items()), guard, check_preconditions)
        if key in self.memo:
            result, safety, domains = self.memo[key]
            self.safety.extend(safety)
            self.domains.extend(domains)
            return result
        safety_start, domains_start = len(self.safety), len(self.domains)
        result = self._call(name, args, kwargs, guard, check_preconditions)
        if not self.assumptions:
            self.memo[key] = (result, self.safety[safety_start:], self.domains[domains_start:])
        return result


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
            active, paths = self.execute(fn.body, [(boolean(guard), env)])
            for path, _ in active:
                self.require(False, path, name + ' return coverage')
            self.require(z3.Or(*(path for path, _ in paths)), guard, name + " return coverage")
            if not paths:
                # A premise can select only a raising or falling-through path.
                # Keep its failed coverage obligation and a typed placeholder
                # so the checker can report the actual counterexample.
                return self.symbol(str(z3.FreshInt('no_return.' + name)), returns)
            for path, result in paths:
                self.require(self.typed(result, returns), path, name + " return type")
            result = paths[-1][1]
            for path, value in reversed(paths[:-1]):
                result = choose(path, value, result, self)
            return result
        finally:
            self.stack.pop()

    def execute(self, statements, active):
        returned = []
        for node in statements:
            next_active = []
            for guard, original in active:
                if self.is_unreachable(guard):
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
                    annotation = (self.source.annotation(node.annotation) if isinstance(node, ast.AnnAssign)
                                  else self.local_types.get(self.stack[-1], {}).get(target.id)
                                  if isinstance(target, ast.Name) else None)
                    if annotation is not None:
                        self.require(self.typed(value, annotation), guard, 'local assignment type')
                        if annotation.kind == 'sequence' and isinstance(value, tuple):
                            value = self.sequence(value, annotation.args[0])
                    if isinstance(target, ast.Name):
                        env[target.id] = value
                    else:
                        if not isinstance(value, tuple) or len(value) != len(target.elts):
                            raise VerificationError("Tuple unpacking arity mismatch")
                        env.update({n.id: v for n, v in zip(target.elts, value)})
                    next_active.append((guard, env))
                elif isinstance(node, ast.If):
                    cond = z3.simplify(self.scalar(self.expr(node.test, env, guard), 'bool', guard))
                    for branch, selected in ((node.body, cond), (node.orelse, z3.Not(cond))):
                        selected_guard = z3.And(guard, selected)
                        if self.is_unreachable(selected_guard):
                            continue
                        ongoing, exits = self.execute(branch, [(selected_guard, env)])
                        next_active.extend(ongoing)
                        returned.extend(exits)
                else:
                    raise VerificationError("Unsupported statement")
            active = next_active
        return active, returned
