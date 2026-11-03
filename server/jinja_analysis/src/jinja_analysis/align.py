"""Line up output templates that differ only in a few places, and share them as one.

Two templates that name files the same way apart from, say, a folder name can be
one template with a field in that place: each user of the template stores its
own text in the field. :func:`align_templates` finds those places (slots), builds
the shared template and proves, for every input, that putting its own text (or
its own expression) back into the slot gives the input's template again.

Templates are compared per path component, the text between two ``/``, so a
slot never spans a folder boundary. A whole folder can be a slot; in the file
name, only the part between two separators (a space, ``-``, ``_``, ``.`` or a
bracket) that differs.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from jinja2 import Environment, TemplateError, nodes

from .expressions import expression_key
from .source import UnsafeEdit, expression_source, template_shape

_SEPARATORS = frozenset(" -_.()[]")


@dataclass(frozen=True)
class Slot:
    key: str
    """``folder``, ``folder_2`` … for a whole folder, ``name``, ``name_2`` … for part of the file name."""
    fallback: str | None
    """The expression the inputs without their own text had in this place, as source, if any."""


@dataclass(frozen=True)
class Alignment:
    template: str
    """The shared template, with a field in every slot."""
    slots: tuple[Slot, ...]
    values: tuple[dict[str, str], ...]
    """Each input's text per slot key; an input that had the fallback expression there has no entry."""


@dataclass(frozen=True)
class AlignmentFailure:
    reason: str
    """Why the templates can't be one, in a short sentence."""


@dataclass(frozen=True)
class _Atom:
    text: str | None = None
    node: nodes.Node | None = field(default=None, compare=False)
    key: object = None

    @classmethod
    def char(cls, char: str) -> "_Atom":
        return cls(text=char, key=("text", char))

    @classmethod
    def expression(cls, node: nodes.Node) -> "_Atom":
        return cls(node=node, key=("expr", expression_key(node)))


@dataclass(frozen=True)
class _Parsed:
    prelude_source: str
    prelude: tuple
    components: tuple[tuple[_Atom, ...], ...]
    tree: nodes.Template


def _prelude_source(source: str, environment: Environment, count: int) -> str:
    """The source of the first ``count`` set tags, which come before any output."""
    if count == 0:
        return ""
    offset = 0
    seen = 0
    tokens = list(environment.lex(source))
    if "".join(value for _, _, value in tokens) != source:
        raise UnsafeEdit()
    for _, kind, value in tokens:
        offset += len(value)
        if kind == "block_end":
            seen += 1
            if seen == count:
                return source[:offset]
    raise UnsafeEdit()


def _parse(source: str, environment: Environment) -> _Parsed:
    tree = environment.parse(source)
    prelude: list[nodes.Assign] = []
    atoms: list[_Atom] = []
    for node in tree.body:
        if isinstance(node, nodes.Assign) and not atoms:
            prelude.append(node)
        elif isinstance(node, nodes.Output):
            for child in node.nodes:
                if isinstance(child, nodes.TemplateData):
                    atoms.extend(_Atom.char(char) for char in child.data)
                else:
                    atoms.append(_Atom.expression(child))
        else:
            raise UnsafeEdit()
    components: list[list[_Atom]] = [[]]
    for atom in atoms:
        if atom.text == "/":
            components.append([])
        else:
            components[-1].append(atom)
    return _Parsed(
        _prelude_source(source, environment, len(prelude)),
        tuple(expression_key(node) for node in prelude),
        tuple(tuple(component) for component in components),
        tree,
    )


def _boundary(atom: _Atom) -> bool:
    return atom.node is not None or atom.text in _SEPARATORS


def _differing_part(members: Sequence[tuple[_Atom, ...]], *, whole_words: bool = True) -> tuple[int, int]:
    """How many atoms all members share at the start and at the end, cut back to separators."""
    shortest = min(len(member) for member in members)
    prefix = 0
    while prefix < shortest and len({member[prefix].key for member in members}) == 1:
        prefix += 1
    suffix = 0
    while suffix < shortest - prefix and len({member[-1 - suffix].key for member in members}) == 1:
        suffix += 1
    if not whole_words:
        return prefix, suffix
    first = members[0]
    while prefix > 0 and not _boundary(first[prefix - 1]):
        prefix -= 1
    while suffix > 0 and not _boundary(first[len(first) - suffix]):
        suffix -= 1
    return prefix, suffix


def _only_whitespace_differs(members: Sequence[tuple[_Atom, ...]]) -> bool:
    prefix, suffix = _differing_part(members, whole_words=False)
    middles = [member[prefix:len(member) - suffix] for member in members]
    return all(atom.text is not None and not atom.text.strip() for middle in middles for atom in middle)


def _source(atoms: Sequence[_Atom]) -> str:
    out: list[str] = []
    for atom in atoms:
        out.append(atom.text if atom.text is not None else "{{ " + expression_source(atom.node) + " }}")
    return "".join(out)


def align_templates(
    templates: Sequence[str],
    environment: Environment,
    *,
    variable: Callable[[str], str],
    typed: Callable[[str], str] = lambda source: source,
    default_fallback: str,
    max_slots: int = 2,
    max_text: int = 255,
) -> Alignment | AlignmentFailure:
    """One template for all of ``templates``, or why there can't be one.

    ``variable(key)`` names the field a slot reads, and ``typed(source)`` wraps
    the field so its text counts as typed text. In a slot where no input had
    an expression, an empty field falls back to ``default_fallback``.
    """
    if not templates:
        return AlignmentFailure("There is no template")
    try:
        parsed = [_parse(template, environment) for template in templates]
    except (TemplateError, UnsafeEdit):
        return AlignmentFailure("A template is not one plain path")
    if len({item.prelude for item in parsed}) != 1:
        return AlignmentFailure("The templates set their variables differently")
    if len({len(item.components) for item in parsed}) != 1:
        return AlignmentFailure("The paths have a different number of folders")

    last = len(parsed[0].components) - 1
    shared: list[str] = []
    slots: list[Slot] = []
    values: list[dict[str, str]] = [{} for _ in parsed]
    pieces: list[list[str]] = [[] for _ in parsed]
    counts = {"folder": 0, "name": 0}
    for index in range(last + 1):
        members = [item.components[index] for item in parsed]
        if len({tuple(atom.key for atom in member) for member in members}) == 1:
            text = _source(members[0])
            shared.append(text)
            for piece in pieces:
                piece.append(text)
            continue
        kind = "name" if index == last else "folder"
        prefix, suffix = (0, 0) if kind == "folder" else _differing_part(members)
        middles = [member[prefix:len(member) - suffix] for member in members]
        expressions = {atom.key: atom.node for middle in middles for atom in middle if atom.node is not None}
        if kind == "folder" and _only_whitespace_differs(members):
            return AlignmentFailure("A folder differs only by a space")
        if len(expressions) > 1 or any(
            any(atom.node is not None for atom in middle) and len(middle) != 1 for middle in middles
        ):
            return AlignmentFailure(
                "A folder differs by more than its text" if kind == "folder" else "The file names differ by more than text"
            )
        texts = ["".join(atom.text for atom in middle) if not any(atom.node for atom in middle) else None
                 for middle in middles]
        if any(text is not None and not text.strip() for text in texts):
            return AlignmentFailure("One differs only by a space or an empty part")
        if any(text is not None and text != text.strip() for text in texts):
            # A leading space is almost always a typo; a field would hide it.
            return AlignmentFailure("The differing text starts or ends with a space")
        if any(text is not None and ("\n" in text or len(text) > max_text) for text in texts):
            return AlignmentFailure(f"The differing text is longer than {max_text} characters")
        counts[kind] += 1
        if sum(counts.values()) > max_slots:
            return AlignmentFailure(f"More than {max_slots} places differ")
        key = kind if counts[kind] == 1 else f"{kind}_{counts[kind]}"
        fallback_node = next(iter(expressions.values()), None)
        fallback = expression_source(fallback_node) if fallback_node is not None else default_fallback
        name = variable(key)
        head, tail = _source(members[0][:prefix]), _source(members[0][len(members[0]) - suffix:])
        shared.append(f"{head}{{{{ ({typed(name)}) if {name} else ({fallback}) }}}}{tail}")
        slots.append(Slot(key, expression_source(fallback_node) if fallback_node is not None else None))
        for position, (member, middle, text) in enumerate(zip(members, middles, texts, strict=True)):
            if text is not None:
                values[position][key] = text
            pieces[position].append(f"{head}{_source(middle)}{tail}")

    template = parsed[0].prelude_source + "/".join(shared)
    try:
        environment.parse(template)
        for item, piece in zip(parsed, pieces, strict=True):
            rebuilt = environment.parse(parsed[0].prelude_source + "/".join(piece))
            if template_shape(rebuilt) != template_shape(item.tree):
                return AlignmentFailure("The shared template would not give the same paths")
    except (TemplateError, UnsafeEdit):
        return AlignmentFailure("The shared template would not give the same paths")
    return Alignment(template, tuple(slots), tuple(values))
