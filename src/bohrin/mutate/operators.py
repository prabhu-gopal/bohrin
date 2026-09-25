"""The built-in mutation operators: the fixed battery of known-wrong candidates.

Deterministic and model-free, so a result is reproducible and costs nothing but reward
invocations. A fixed battery finds real defects; it does not find what a motivated attacker
searching one specific grader finds, and that limit is stated rather than disguised.

Every operator here targets a class in the weakness list (``docs/WEAKNESSES.md``) and either
establishes a :class:`~bohrin.ir.task.Ground`, emits an explicitly ungrounded candidate that
can only ever become a lead, or declines to emit at all. Nothing here may claim a ground it
cannot support: a ground is a claim about the candidate's *behaviour*, and a difference in
*source* is not evidence of one. See ``docs/SPEC.md`` and :mod:`bohrin.mutate.equivalence`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import libcst as cst

from bohrin.ir.task import Candidate, Ground, Provenance, Shape, Source, Task
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.equivalence import code_equivalent


def _cand(op: str, base: str, detail: str, payload: str, ground: Ground | None) -> Candidate:
    return Candidate(
        payload=Source(payload), provenance=Provenance(operator=op, base=base, detail=detail), ground=ground
    )


class _BodyStripper(cst.CSTTransformer):
    """Replace every function body with a single ``pass``."""

    def __init__(self) -> None:
        self.changed = False

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Replace this function's body; its signature, decorators and name are kept."""
        self.changed = True
        return updated_node.with_changes(body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[cst.Pass()])]))


def _inert(statement: cst.BaseSmallStatement) -> bool:
    """A statement that does nothing: ``pass``, ``...``, a bare string or number, a bare name, or
    ``raise NotImplementedError``.

    A bare name is inert only in the sense that matters here: evaluating it changes nothing, so a
    function whose body is ``x`` does exactly what ``pass`` does whenever it runs at all.
    """
    if isinstance(statement, cst.Pass):
        return True
    if isinstance(statement, cst.Expr):
        return isinstance(
            statement.value,
            cst.Ellipsis | cst.SimpleString | cst.ConcatenatedString | cst.Integer | cst.Float | cst.Name,
        )
    if isinstance(statement, cst.Raise) and statement.exc is not None:
        raised = statement.exc.func if isinstance(statement.exc, cst.Call) else statement.exc
        return isinstance(raised, cst.Name) and raised.value == "NotImplementedError"
    return False


class _WorkFinder(cst.CSTVisitor):
    """Records whether any function in a module has a body that does work."""

    def __init__(self) -> None:
        self.does_work = False

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Mark the module as doing work if this function's body holds anything but no-ops."""
        body = node.body
        lines = body.body if isinstance(body, cst.IndentedBlock) else [body]
        for line in lines:
            # A nested function or class is not work in itself: its own methods and functions are
            # visited separately, and count as work only if their bodies do something.
            if isinstance(line, cst.FunctionDef | cst.ClassDef):
                continue
            if not (
                isinstance(line, cst.SimpleStatementLine | cst.SimpleStatementSuite) and all(map(_inert, line.body))
            ):
                self.does_work = True


def _parse(source: str) -> cst.Module | None:
    try:
        return cst.parse_module(source)
    except Exception:  # not Python, or not parseable — the operator simply does not apply
        return None


class DropSideEffect(MutationOperator):
    """Empty every function body, keeping the signature (BGW-101, trivial implementation).

    A grader that checks only that the code imports and runs, or that checks a return value
    but never the filesystem or database, accepts a solution that does no work.

    **The ground needs a reference that does work.** "The emptied program does no work" proves
    it wrong only if the reference does some. An interface, an abstract base class or a protocol
    has functions whose bodies are only docstrings, ``pass``, ``...`` or ``raise
    NotImplementedError``; emptying them removes nothing, and a correct grader of that interface
    is right to accept the result. So the operator stays silent unless at least one function in
    the reference does something else.
    """

    id = "drop_side_effect"
    category = "hollow_program"
    rationale = "The signature survives but the work does not, so only a verifier that checks effects can catch it."
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The reference with every function body emptied, or nothing if that proves nothing."""
        source = task.reference or ""
        module = _parse(source)
        if module is None:
            return
        finder = _WorkFinder()
        module.visit(finder)
        if not finder.does_work:
            return
        tf = _BodyStripper()
        mutated = module.visit(tf)
        # `changed` only records that the transformer fired. A reference whose bodies
        # are already `pass` produces a mutant identical to the reference, which the
        # verifier has just accepted as the known-good answer — reporting that as an
        # exploit accuses a verifier of accepting the correct solution.
        if not tf.changed or code_equivalent(mutated.code, source):
            return
        yield _cand(
            self.id,
            "reference",
            "every function body replaced with `pass`; no work is performed",
            mutated.code,
            Ground.STRUCTURAL,
        )


class _RaisingBodies(cst.CSTTransformer):
    """Replace every function body with ``raise NotImplementedError``."""

    def __init__(self) -> None:
        self.changed = False

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Replace this function's body; its signature, decorators and name are kept."""
        self.changed = True
        raising = cst.Raise(exc=cst.Name("NotImplementedError"))
        return updated_node.with_changes(body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[raising])]))


def _statements(function: cst.FunctionDef) -> list[cst.CSTNode]:
    """The function's own statements, small statements unpacked, nested definitions left out."""
    body = function.body
    lines = body.body if isinstance(body, cst.IndentedBlock) else [body]
    out: list[cst.CSTNode] = []
    for line in lines:
        if isinstance(line, cst.SimpleStatementLine | cst.SimpleStatementSuite):
            out.extend(line.body)
        elif not isinstance(line, cst.FunctionDef | cst.ClassDef):
            out.append(line)
    return out


class _BeyondRaising(cst.CSTVisitor):
    """Records whether any function does work other than raising an error."""

    def __init__(self) -> None:
        self.found = False

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """A statement that is neither inert nor a ``raise`` is work beyond raising. Nothing after an
        unconditional ``raise`` can run, so it is not work."""
        for statement in _statements(node):
            if isinstance(statement, cst.Raise):
                break
            if isinstance(statement, cst.BaseSmallStatement) and _inert(statement):
                continue
            self.found = True


class RaiseNotImplemented(MutationOperator):
    """Replace every function body with ``raise NotImplementedError`` (BGW-101, trivial implementation).

    A grader that treats an exception as a pass, or checks only that the code imports, pays for a
    solution that refuses to do anything.

    **The ground needs a reference that does work, and work other than raising.** An interface's
    functions already raise ``NotImplementedError``; a reference whose only work is raising some
    other error (a validator that always refuses, say) differs from this one only in which error
    it raises, which a correct grader may not distinguish. In both cases nothing is submitted.
    """

    id = "raise_not_implemented"
    category = "hollow_program"
    rationale = "Every function refuses to run, so only a grader that checks results can catch it."
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The reference with every function body raising, or nothing if that proves nothing."""
        source = task.reference or ""
        module = _parse(source)
        if module is None:
            return
        finder = _WorkFinder()
        module.visit(finder)
        beyond = _BeyondRaising()
        module.visit(beyond)
        if not (finder.does_work and beyond.found):
            return
        tf = _RaisingBodies()
        mutated = module.visit(tf)
        if not tf.changed or code_equivalent(mutated.code, source):
            return
        yield _cand(
            self.id,
            "reference",
            "every function body replaced with `raise NotImplementedError`; no work is performed",
            mutated.code,
            Ground.STRUCTURAL,
        )


#: The constant each return type gets: the value a check of the type alone accepts.
_CONSTANT_OF_TYPE = {
    "int": "0",
    "float": "0.0",
    "complex": "0j",
    "str": '""',
    "bytes": 'b""',
    "bool": "False",
    "list": "[]",
    "sequence": "[]",
    "dict": "{}",
    "mapping": "{}",
    "set": "set()",
    "frozenset": "frozenset()",
    "tuple": "()",
    "none": "None",
}

#: Built-in calls whose result type is fixed, by the name of the type.
_CALL_TYPES = {
    "len": "int",
    "int": "int",
    "round": "int",
    "float": "float",
    "str": "str",
    "repr": "str",
    "bool": "bool",
    "isinstance": "bool",
    "all": "bool",
    "any": "bool",
    "list": "list",
    "sorted": "list",
    "dict": "dict",
    "set": "set",
    "frozenset": "frozenset",
    "tuple": "tuple",
    "bytes": "bytes",
}


def _one_type(kinds: Iterable[str | None]) -> str | None:
    """The single type among those known, or None when none is known or two differ."""
    known = {kind for kind in kinds if kind is not None}
    return known.pop() if len(known) == 1 else None


def _type_of_annotation(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.Subscript):
        node = node.value
    if isinstance(node, cst.Attribute):
        node = node.attr
    if isinstance(node, cst.Name) and node.value.lower() in _CONSTANT_OF_TYPE:
        return node.value.lower()
    return None


def _type_of_value(
    node: cst.BaseExpression, assigned: dict[str, list[cst.BaseExpression]], depth: int = 0
) -> str | None:
    """The type a returned expression certainly has, or None when the syntax does not say.

    A local name has the one type its assigned values show; values whose type the syntax does not
    show are passed over, and two different types mean none.
    """
    if isinstance(node, cst.UnaryOperation) and isinstance(node.operator, cst.Minus | cst.Plus):
        inner = _type_of_value(node.expression, assigned, depth)
        return inner if inner in ("int", "float", "complex") else None
    if isinstance(node, cst.Integer):
        return "int"
    if isinstance(node, cst.Float):
        return "float"
    if isinstance(node, cst.Imaginary):
        return "complex"
    if isinstance(node, cst.SimpleString | cst.ConcatenatedString | cst.FormattedString):
        prefix = node.prefix.lower() if isinstance(node, cst.SimpleString | cst.FormattedString) else ""
        return "bytes" if "b" in prefix else "str"
    if isinstance(node, cst.List | cst.ListComp):
        return "list"
    if isinstance(node, cst.Dict | cst.DictComp):
        return "dict"
    if isinstance(node, cst.Set | cst.SetComp):
        return "set"
    if isinstance(node, cst.Tuple):
        return "tuple"
    if isinstance(node, cst.Comparison) or (
        isinstance(node, cst.UnaryOperation) and isinstance(node.operator, cst.Not)
    ):
        return "bool"
    if isinstance(node, cst.Call) and isinstance(node.func, cst.Name):
        return _CALL_TYPES.get(node.func.value)
    if isinstance(node, cst.Name):
        if node.value in ("True", "False"):
            return "bool"
        if node.value == "None":
            return "none"
        if node.value in assigned and depth < 5:
            return _one_type(_type_of_value(value, assigned, depth + 1) for value in assigned[node.value])
    return None


class _Returns(cst.CSTVisitor):
    """A function's own return values, and the first value assigned to each local name."""

    def __init__(self) -> None:
        self.values: list[cst.BaseExpression | None] = []
        #: Every value assigned to each simple local name, so a name reassigned to another type has none.
        self.assigned: dict[str, list[cst.BaseExpression]] = {}
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        """Nested functions have returns of their own: they are not this function's."""
        return False

    def visit_Lambda(self, node: cst.Lambda) -> bool:
        """A lambda's value is not this function's return value."""
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        """Methods of a nested class are not this function's."""
        return False

    def visit_Return(self, node: cst.Return) -> None:
        """Record what is returned (None for a bare return)."""
        self.values.append(node.value)

    def visit_Assign(self, node: cst.Assign) -> None:
        """Remember every value each simple name is given."""
        for target in node.targets:
            if isinstance(target.target, cst.Name):
                self.assigned.setdefault(target.target.value, []).append(node.value)

    def visit_Name(self, node: cst.Name) -> None:
        """Every name the body mentions, to tell whether it reads its parameters."""
        self.names.add(node.value)


_LITERALS = (
    cst.Integer,
    cst.Float,
    cst.Imaginary,
    cst.SimpleString,
    cst.ConcatenatedString,
)


def _is_literal(node: cst.BaseExpression | None) -> bool:
    """A value the syntax fixes: a number (signed or not), a plain string, True, False, None, or an empty
    collection."""
    if node is None or isinstance(node, _LITERALS):
        return True
    if isinstance(node, cst.UnaryOperation) and isinstance(node.operator, cst.Minus | cst.Plus):
        return isinstance(node.expression, cst.Integer | cst.Float | cst.Imaginary)
    if isinstance(node, cst.Name):
        return node.value in ("True", "False", "None")
    if isinstance(node, cst.List | cst.Tuple | cst.Set):
        return not node.elements
    if isinstance(node, cst.Dict):
        return not node.elements
    return False


class _ConstantBodies(cst.CSTTransformer):
    """Replace every function body with ``return <constant>`` of the type it returns.

    Special methods are left as they are: their return types are fixed by Python, not the task.
    """

    def __init__(self) -> None:
        self.constants: list[str] = []
        #: Some replaced function read its parameters and returned something the syntax does not fix.
        self.grounded = False

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Replace this function's body with a constant of its return type."""
        name = original_node.name.value
        if name.startswith("__") and name.endswith("__"):
            return updated_node
        returns = _Returns()
        for line in original_node.body.body if isinstance(original_node.body, cst.IndentedBlock) else []:
            line.visit(returns)
        kind = _type_of_annotation(original_node.returns.annotation) if original_node.returns else None
        if kind is None:
            kind = _one_type(_type_of_value(v, returns.assigned) if v is not None else "none" for v in returns.values)
        constant = _CONSTANT_OF_TYPE.get(kind or "none", "None")
        self.constants.append(constant)
        # ``self`` and ``cls`` are inputs too: a method reading ``self.n`` depends on the object.
        parameters = {
            p.name.value
            for p in (
                *original_node.params.params,
                *original_node.params.posonly_params,
                *original_node.params.kwonly_params,
            )
        }
        reads_inputs = bool(parameters & returns.names)
        computes = any(not _is_literal(v) for v in returns.values)
        self.grounded = self.grounded or (reads_inputs and computes)
        statement = cst.Return(value=cst.parse_expression(constant))
        return updated_node.with_changes(body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[statement])]))


class ConstantImplementation(MutationOperator):
    """Make every function return a constant of its own return type (BGW-101, trivial implementation).

    ``0`` for a function returning a count, ``""`` for text, ``[]`` for a list: a grader that checks
    only the type, or only that the call succeeds, pays for it. The type comes from the return
    annotation, or else from what the reference itself returns (``total = 0 … return total`` is
    an ``int``); where neither says, the constant is ``None``.

    **The ground needs a reference whose result depends on its inputs.** If no function reads its
    parameters and returns a computed value, the reference may itself return this constant, so
    the submission is a lead, never counted. If every constant would be ``None``, the submission is
    the empty implementation again and nothing is submitted.
    """

    id = "constant_implementation"
    category = "hollow_program"
    rationale = "The result has the right type and never the right value, so only a check of values catches it."
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The reference with every function returning a type-correct constant."""
        source = task.reference or ""
        module = _parse(source)
        if module is None:
            return
        finder = _WorkFinder()
        module.visit(finder)
        if not finder.does_work:
            return
        tf = _ConstantBodies()
        mutated = module.visit(tf)
        if all(c == "None" for c in tf.constants) or code_equivalent(mutated.code, source):
            return
        ground = Ground.STRUCTURAL if tf.grounded else None
        detail = (
            f"every function returns a constant of its type ({', '.join(sorted(set(tf.constants)))}), "
            "whatever its inputs"
        )
        if ground is None:
            detail += "; a lead: no function of the reference reads its inputs and computes its result"
        yield _cand(self.id, "reference", detail, mutated.code, ground)


# Negating a condition, perturbing a boundary by one, or swapping an operator (`<` for `<=`,
# `+` for `-`) is deliberately absent: a changed source is not evidence of changed behaviour,
# so none of them could establish wrongness without executing both programs on a
# differentiating input.

__all__ = ["ConstantImplementation", "DropSideEffect", "RaiseNotImplemented"]
