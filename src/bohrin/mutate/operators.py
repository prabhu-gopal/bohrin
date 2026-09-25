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

from bohrin.ir.task import Candidate, Ground, Provenance, Shape, Source, Task, Workspace
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.equivalence import code_equivalent


def _cand(op: str, base: str, detail: str, payload: str, ground: Ground | None) -> Candidate:
    return Candidate(
        payload=Source(payload), provenance=Provenance(operator=op, base=base, detail=detail), ground=ground
    )


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


def _does_work(function: cst.FunctionDef) -> bool:
    """Whether this function's own body holds anything but no-ops.

    A nested function or class is not work in itself: it counts only where something calls it, and
    a call is work of the function making it.
    """
    body = function.body
    lines = body.body if isinstance(body, cst.IndentedBlock) else [body]
    for line in lines:
        if isinstance(line, cst.FunctionDef | cst.ClassDef):
            continue
        if not (isinstance(line, cst.SimpleStatementLine | cst.SimpleStatementSuite) and all(map(_inert, line.body))):
            return True
    return False


def _special(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


class _Names(cst.CSTVisitor):
    """Every name a piece of code mentions, bare or as an attribute (``self.helper``)."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: cst.Name) -> None:
        """Record the name."""
        self.names.add(node.value)


def _names_in(node: cst.CSTNode) -> set[str]:
    names = _Names()
    node.visit(names)
    return names.names


class _ModuleLevel(cst.CSTVisitor):
    """What runs when the module itself runs: the names it mentions, and whether it does work.

    Function bodies are not module-level code; their decorators are. A class body runs at import,
    so the names in it count, but a class body is never the program's output: only a bare
    expression outside every class and function (a call, typically) makes the module a script.
    A bare name can reach a module-level definition; an attribute (``obj.run``) only a member.
    """

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.attributes: set[str] = set()
        self.runs = False
        self._in_class = 0

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        """Only the decorators run here."""
        for decorator in node.decorators:
            decorator.visit(self)
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        """Everything but the class's own name, which is a definition, not a use."""
        for part in (*node.decorators, *node.bases, *node.keywords):
            part.visit(self)
        self._in_class += 1
        node.body.visit(self)
        self._in_class -= 1
        return False

    def visit_Expr(self, node: cst.Expr) -> None:
        """A bare expression that is not inert is the module doing work of its own."""
        if not self._in_class and not _inert(node):
            self.runs = True

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        """Record the attribute's name apart from bare names; what it is read from is ordinary code."""
        self.attributes.add(node.attr.value)
        node.value.visit(self)
        return False

    def visit_Name(self, node: cst.Name) -> None:
        """Record the name."""
        self.names.add(node.value)


class _Definitions(cst.CSTVisitor):
    """Every function a grader could reach without entering another function: module-level functions,
    and methods of module-level classes (nested classes included), each with the class that owns it."""

    def __init__(self) -> None:
        self.functions: list[tuple[cst.FunctionDef, cst.ClassDef | None]] = []
        self.classes: list[tuple[cst.ClassDef, cst.ClassDef | None]] = []
        self._owner: list[cst.ClassDef] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        """Record it; what it nests is part of it."""
        self.functions.append((node, self._owner[-1] if self._owner else None))
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Record it, and own the functions inside."""
        self.classes.append((node, self._owner[-1] if self._owner else None))
        self._owner.append(node)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        """Stop owning."""
        self._owner.pop()


def _reached(name: str, owner: cst.ClassDef | None, names: set[str], members: set[str], classes: set[int]) -> bool:
    """A module-level definition is reached when named; a class member when its class is reached and
    it is public, special, or named as a name or an attribute."""
    if owner is None:
        return name in names
    return id(owner) in classes and (not name.startswith("_") or _special(name) or name in names | members)


def _live(module: cst.Module) -> set[int]:
    """The functions (by ``id``) a grader can call, or that run when the module runs.

    Emptying a function nothing ever calls changes nothing, so the ground of a hollow program needs
    the removed work to be *reachable*. Where it starts depends on what the module is:

    * **A script** (module-level code does work, such as ``print(...)`` or ``main()``): only what
      that code names. A grader may judge it by what it prints, and a function it never names may be
      dead code.
    * **A library** (module-level code only defines): its public functions and classes too, since a
      grader imports it and calls them, and its special functions (``__getattr__``), which Python
      calls.

    A reached class's public and special methods are reached too, and so is any member the
    module-level code names. A function reached only because another calls it is not counted: the
    call is work of the caller, which is reached, and its result is seen only through the caller.
    Reachability is by name: a module-level function is reached by a bare name, never by an
    attribute of something else (``thread.run()`` does not reach a function ``run``). A name rebound
    at module level to something else still counts as reaching the function it once named.
    """
    top = _ModuleLevel()
    module.visit(top)
    found = _Definitions()
    module.visit(found)
    names = set(top.names)
    if not top.runs:
        defined = [f.name.value for f, owner in found.functions if owner is None]
        defined += [c.name.value for c, owner in found.classes if owner is None]
        # A module-level special function (``__getattr__``, ``__dir__``) is called by Python itself.
        names |= {name for name in defined if not name.startswith("_") or _special(name)}
    # A class is recorded before the classes nested in it, so one pass reaches every level.
    classes: set[int] = set()
    for cls, owner in found.classes:
        if _reached(cls.name.value, owner, names, top.attributes, classes):
            classes.add(id(cls))
    return {
        id(function)
        for function, owner in found.functions
        if _reached(function.name.value, owner, names, top.attributes, classes)
    }


def _reachable(module: cst.Module) -> list[cst.FunctionDef]:
    """The reachable functions themselves (see :func:`_live`)."""
    found = _Definitions()
    module.visit(found)
    live = _live(module)
    return [function for function, _ in found.functions if id(function) in live]


def _live_work(module: cst.Module) -> list[cst.FunctionDef]:
    """The reachable functions that do work of their own: what a hollow program provably removes."""
    return [function for function in _reachable(module) if _does_work(function)]


def _parse(source: str) -> cst.Module | None:
    try:
        return cst.parse_module(source)
    except Exception:  # not Python, or not parseable — the operator simply does not apply
        return None


class _ReplacedBodies(cst.CSTTransformer):
    """Replace every function body, special methods included, with the same statements.

    Special methods are replaced too: one left as it was could keep all of the reference's work (a
    class whose only work is ``__add__``), and a grader checking only that would rightly accept.
    """

    def __init__(self, body: str) -> None:
        self.body = cst.parse_module(body).body

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Replace this function's body; its signature, decorators and name are kept."""
        return updated_node.with_changes(body=cst.IndentedBlock(body=self.body))


def _hollow(source: str, body: str) -> str | None:
    """The reference with every function body replaced by ``body``, or None where that proves nothing:
    the reference does not parse, no reachable function does work, or the result is the reference."""
    module = _parse(source)
    if module is None or not _live_work(module):
        return None
    mutated = module.visit(_ReplacedBodies(body)).code
    # A reference whose bodies already are ``body`` gives back the reference, which the grader has
    # just accepted as the known-good answer: reporting that would accuse it of accepting the
    # correct solution.
    return None if code_equivalent(mutated, source) else mutated


class DropSideEffect(MutationOperator):
    """Empty every function body, keeping the signature (BGW-101, trivial implementation).

    A grader that checks only that the code imports and runs, or that checks a return value
    but never the filesystem or database, accepts a solution that does no work.

    **The ground needs a reference that does work.** "The emptied program does no work" proves
    it wrong only if the reference does some. An interface, an abstract base class or a protocol
    has functions whose bodies are only docstrings, ``pass``, ``...`` or ``raise
    NotImplementedError``; emptying them removes nothing, and a correct grader of that interface
    is right to accept the result. So the operator stays silent unless at least one function in
    the reference does something else, and that function is reachable (see :func:`_live`): emptying
    a helper nothing calls changes nothing a correct grader can see.
    """

    id = "drop_side_effect"
    category = "hollow_program"
    rationale = "The signature survives but the work does not, so only a verifier that checks effects can catch it."
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The reference with every function body emptied, or nothing if that proves nothing."""
        mutated = _hollow(task.reference or "", "pass\n")
        if mutated is None:
            return
        yield _cand(
            self.id,
            "reference",
            "every function body replaced with `pass`; no work is performed",
            mutated,
            Ground.STRUCTURAL,
        )


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


def _beyond_raising(function: cst.FunctionDef) -> bool:
    """Whether the function does work other than raising an error: a statement that is neither inert
    nor a ``raise``. Nothing after an unconditional ``raise`` can run, so it is not work."""
    for statement in _statements(function):
        if isinstance(statement, cst.Raise):
            return False
        if not (isinstance(statement, cst.BaseSmallStatement) and _inert(statement)):
            return True
    return False


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
        # Work beyond raising cannot survive every body raising, so the result is never the reference.
        if module is None or not any(map(_beyond_raising, _reachable(module))):
            return
        mutated = module.visit(_ReplacedBodies("raise NotImplementedError\n")).code
        yield _cand(
            self.id,
            "reference",
            "every function body replaced with `raise NotImplementedError`; no work is performed",
            mutated,
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

    def __init__(self, live: set[int]) -> None:
        #: The functions whose work a grader can observe (see :func:`_live`), by ``id``.
        self.live = live
        self.constants: list[str] = []
        #: Some reachable replaced function read its parameters and returned something the syntax does not fix.
        self.grounded = False
        #: Some reachable special method, kept as it is, does work: a grader may be judging only that.
        self.kept_work = False

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Replace this function's body with a constant of its return type."""
        live = id(original_node) in self.live
        if _special(original_node.name.value):
            self.kept_work = self.kept_work or (live and _does_work(original_node))
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
        self.grounded = self.grounded or (live and reads_inputs and computes)
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
    the submission is a lead, never counted. Only reachable functions count (see :func:`_live`),
    and a reachable special method that does work makes it a lead too: special methods keep their
    bodies, so their work survives, and a correct grader may be checking only that. If every
    constant would be ``None``, the submission is the empty implementation again and nothing is
    submitted.
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
        if not _live_work(module):
            return
        tf = _ConstantBodies(_live(module))
        mutated = module.visit(tf)
        if all(c == "None" for c in tf.constants) or code_equivalent(mutated.code, source):
            return
        ground = Ground.STRUCTURAL if tf.grounded and not tf.kept_work else None
        detail = (
            f"every function returns a constant of its type ({', '.join(sorted(set(tf.constants)))}), "
            "whatever its inputs"
        )
        if tf.kept_work:
            detail += "; a lead: a special method, which keeps its body, does work of its own"
        elif ground is None:
            detail += "; a lead: no function of the reference reads its inputs and computes its result"
        yield _cand(self.id, "reference", detail, mutated.code, ground)


# Negating a condition, perturbing a boundary by one, or swapping an operator (`<` for `<=`,
# `+` for `-`) is deliberately absent: a changed source is not evidence of changed behaviour,
# so none of them could establish wrongness without executing both programs on a
# differentiating input.


class SuccessExit(MutationOperator):
    """Replace every function body with ``sys.exit(0)`` (BGW-102, exit before the checks).

    A grader that reads a zero exit status as success, without a positive record that the checks
    ran, pays for a program that ends cleanly before any of them.

    **It ends the process that runs it.** A grader, or a loop around one, that runs submissions in
    its own process and catches only ``Exception`` stops at this one with exit status 0. Run each
    submission in a process of its own, as a grader of untrusted code must anyway.

    The ground is the empty implementation's: every function body is replaced, special methods
    included, so it needs a reachable function that does work.
    """

    id = "success_exit"
    category = "hollow_program"
    rationale = (
        "The program exits cleanly before any check can run, so only a verifier that looks for a "
        "positive record of the checks catches it."
    )
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The reference with every function body exiting with status 0, or nothing if that proves nothing."""
        mutated = _hollow(task.reference or "", "import sys\nsys.exit(0)\n")
        if mutated is None:
            return
        yield _cand(
            self.id,
            "reference",
            "every function body replaced with `sys.exit(0)`; no work is performed",
            mutated,
            Ground.STRUCTURAL,
        )


def _preamble(module: cst.Module) -> int:
    """How many leading statements must stay first: the module docstring and ``from __future__`` imports."""
    index = 0
    body = module.body
    if (
        body
        and isinstance(body[0], cst.SimpleStatementLine)
        and len(body[0].body) == 1
        and isinstance(body[0].body[0], cst.Expr)
        and isinstance(body[0].body[0].value, cst.SimpleString | cst.ConcatenatedString)
    ):
        index = 1
    while index < len(body) and _future_import(body[index]):
        index += 1
    return index


def _future_import(line: cst.BaseStatement) -> bool:
    """A line with a ``from __future__`` import in it, alone or beside other statements."""
    return isinstance(line, cst.SimpleStatementLine) and any(
        isinstance(s, cst.ImportFrom) and isinstance(s.module, cst.Name) and s.module.value == "__future__"
        for s in line.body
    )


class EqualitySpoofing(MutationOperator):
    """Make every function return an object that equals everything (BGW-103, equality spoofing).

    A grader that compares a result with ``==`` and never checks its type pays for an object whose
    ``__eq__`` always says yes.

    The ground is the empty implementation's: every function body is replaced, special methods
    included, so it needs a reachable function that does work. The spoofing class takes a name the
    reference does not use, and goes after its docstring and ``from __future__`` imports.
    """

    id = "equality_spoofing"
    category = "hollow_program"
    rationale = "The returned object claims to equal everything, so only a check of its exact type or value catches it."
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The reference with every function returning a spoofed object, or nothing if that proves nothing."""
        source = task.reference or ""
        module = _parse(source)
        if module is None:
            return
        name = "_Spoof"
        used = _names_in(module)
        while name in used:
            name += "_"
        mutated = _hollow(source, f"return {name}()\n")
        if mutated is None:
            return
        spoof = cst.parse_statement(
            f"class {name}:\n"
            "    def __eq__(self, other):\n        return True\n"
            "    def __ne__(self, other):\n        return False\n"
            "    def __getattr__(self, name):\n        return lambda *a, **k: self\n"
        )
        hollow = cst.parse_module(mutated)
        at = _preamble(hollow)
        yield _cand(
            self.id,
            "reference",
            "every function returns an object that equals everything; no work is performed",
            hollow.with_changes(body=[*hollow.body[:at], spoof, *hollow.body[at:]]).code,
            Ground.STRUCTURAL,
        )


def _tampered(operator: str, task: Task, conftest: str, detail: str) -> Iterator[Candidate]:
    """The empty implementation at ``{source_path}``, with ``conftest`` written into ``{test_root}``.

    The ground is the empty implementation's, established without the tamper: the solution does no
    work, so whatever the tests report, a correct grader rejects it. The tamper is what a weak one
    pays for.
    """
    hollow = _hollow(task.reference or "", "pass\n")
    if hollow is None:
        return
    workspace = Workspace(
        files={"{test_root}/conftest.py": conftest, "{source_path}": hollow},
        parameters=("test_root", "source_path"),
    )
    yield Candidate(payload=workspace, provenance=Provenance(operator, "reference", detail), ground=Ground.STRUCTURAL)


class TestFrameworkHook(MutationOperator):
    """Patch pytest to report every test as passed (BGW-108, test-framework hook).

    A ``conftest.py`` in the test directory wraps pytest's report hook and marks every outcome
    passed, beside the empty implementation. A grader that runs the tests in the submitted tree and
    trusts pytest's verdict pays for it.
    """

    id = "test_framework_hook"
    category = "harness_tampering"
    rationale = (
        "The test framework is patched to report success whatever happens, so only a verifier that runs "
        "its tests apart from the submission catches it."
    )
    requires_code = True
    shapes = (Shape.WORKSPACE, Shape.CONTAINER, Shape.HISTORY)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The empty implementation with a conftest.py that marks every test passed."""
        conftest = (
            "import pytest\n\n\n"
            "@pytest.hookimpl(hookwrapper=True)\n"
            "def pytest_runtest_makereport(item, call):\n"
            "    outcome = yield\n"
            '    outcome.get_result().outcome = "passed"\n'
        )
        yield from _tampered(self.id, task, conftest, "pytest is patched to report every test as passed")


class TestsDeleted(MutationOperator):
    """Deselect every test (BGW-109, tests edited, deleted or skipped).

    A ``conftest.py`` in the test directory empties pytest's collection, beside the empty
    implementation. Nothing runs, so nothing fails: a grader that counts failures, or treats pytest's
    "no tests ran" status as a pass, pays for it.
    """

    id = "tests_deleted"
    category = "harness_tampering"
    rationale = (
        "The tests are deselected, so only a verifier that checks how many tests ran, or runs its tests "
        "apart from the submission, catches it."
    )
    requires_code = True
    shapes = (Shape.WORKSPACE, Shape.CONTAINER, Shape.HISTORY)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The empty implementation with a conftest.py that deselects every test."""
        conftest = "def pytest_collection_modifyitems(config, items):\n    items.clear()\n"
        yield from _tampered(self.id, task, conftest, "pytest is told to run no tests")


__all__ = [
    "ConstantImplementation",
    "DropSideEffect",
    "EqualitySpoofing",
    "RaiseNotImplemented",
    "SuccessExit",
    "TestFrameworkHook",
    "TestsDeleted",
]
