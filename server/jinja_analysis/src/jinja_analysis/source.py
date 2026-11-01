"""Print Jinja expressions as source, and edit templates one tag at a time.

Every caller re-parses what it gets back and compares it with the intended
tree, so a printed expression or an edited template is only ever used when it
means exactly what was meant. Untouched code and comments stay byte-exact.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math

from jinja2 import Environment, TemplateError, nodes
from jinja2.visitor import NodeTransformer

from .expressions import expression_key


class UnsafeEdit(Exception):
    """The expression or edit cannot be printed or applied exactly."""


@dataclass(frozen=True)
class TemplateEdit:
    before: str
    """The changed part of the template as it was, with its enclosing blocks."""
    after: str
    """The same part after the edit."""
    output_template: str
    """The whole edited template."""


# How tightly each expression binds, following Jinja's parser from
# parse_condexpr down to parse_unary. Filters and tests apply to a unary.
_CONDITION, _OR, _AND, _NOT, _COMPARE, _ADD, _CONCAT, _MUL, _POW, _UNARY, _PRIMARY = range(11)
_BINARY = {
    nodes.Or: ("or", _OR), nodes.And: ("and", _AND),
    nodes.Add: ("+", _ADD), nodes.Sub: ("-", _ADD),
    nodes.Mul: ("*", _MUL), nodes.Div: ("/", _MUL), nodes.FloorDiv: ("//", _MUL), nodes.Mod: ("%", _MUL),
    nodes.Pow: ("**", _POW),
}
_COMPARISONS = {"eq": "==", "ne": "!=", "lt": "<", "lteq": "<=", "gt": ">", "gteq": ">=", "in": "in", "notin": "not in"}


def _const(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        raise UnsafeEdit()
    if isinstance(value, (str, int, float)):
        return repr(value)
    raise UnsafeEdit()


def _arguments(node: nodes.Call | nodes.Filter | nodes.Test) -> str:
    if node.dyn_args is not None or node.dyn_kwargs is not None:
        raise UnsafeEdit()
    args = [expression_source(item) for item in node.args]
    args.extend(f"{item.key}={expression_source(item.value)}" for item in node.kwargs)
    return ", ".join(args)


def _printed(node: nodes.Node) -> tuple[str, int]:
    if isinstance(node, nodes.Const):
        text = _const(node.value)
        return text, _UNARY if text.startswith("-") else _PRIMARY
    if isinstance(node, nodes.Name):
        return node.name, _PRIMARY
    if isinstance(node, nodes.Concat):
        if not node.nodes:
            raise UnsafeEdit()
        return " ~ ".join(_operand(item, _MUL) for item in node.nodes), _CONCAT
    if type(node) in _BINARY:
        operator, level = _BINARY[type(node)]
        return f"{_operand(node.left, level)} {operator} {_operand(node.right, level + 1)}", level
    if isinstance(node, nodes.Not):
        return "not " + _operand(node.node, _NOT), _NOT
    if isinstance(node, (nodes.Neg, nodes.Pos)):
        return ("-" if isinstance(node, nodes.Neg) else "+") + _operand(node.node, _PRIMARY), _UNARY
    if isinstance(node, nodes.Compare):
        text = _operand(node.expr, _COMPARE + 1)
        for item in node.ops:
            text += f" {_COMPARISONS[item.op]} {_operand(item.expr, _COMPARE + 1)}"
        return text, _COMPARE
    if isinstance(node, nodes.CondExpr):
        text = f"{_operand(node.expr1, _OR)} if {_operand(node.test, _OR)}"
        if node.expr2 is not None:
            text += " else " + _operand(node.expr2, _CONDITION)
        return text, _CONDITION
    if isinstance(node, (nodes.Filter, nodes.Test)):
        if node.node is None:
            raise UnsafeEdit()
        arguments = _arguments(node)
        operator = " | " if isinstance(node, nodes.Filter) else " is "
        tail = f"({arguments})" if arguments else ""
        return _operand(node.node, _UNARY) + operator + node.name + tail, _UNARY
    if isinstance(node, nodes.Getattr):
        return f"{_operand(node.node, _PRIMARY)}.{node.attr}", _PRIMARY
    if isinstance(node, nodes.Getitem):
        return f"{_operand(node.node, _PRIMARY)}[{expression_source(node.arg)}]", _PRIMARY
    if isinstance(node, nodes.Call):
        return f"{_operand(node.node, _PRIMARY)}({_arguments(node)})", _PRIMARY
    if isinstance(node, nodes.List):
        return "[" + ", ".join(expression_source(item) for item in node.items) + "]", _PRIMARY
    if isinstance(node, nodes.Tuple):
        items = [expression_source(item) for item in node.items]
        return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")", _PRIMARY
    if isinstance(node, nodes.Dict):
        return "{" + ", ".join(
            f"{expression_source(item.key)}: {expression_source(item.value)}" for item in node.items
        ) + "}", _PRIMARY
    raise UnsafeEdit()


def _operand(node: nodes.Node, level: int) -> str:
    text, own = _printed(node)
    return f"({text})" if own < level else text


def expression_source(node: nodes.Node) -> str:
    """Print an expression as Jinja source, with only the brackets it needs.

    Raises UnsafeEdit for anything that is not a plain expression.
    """
    return _printed(node)[0]


def all_nodes(node: nodes.Node, cls) -> list:
    """``node`` itself when it is a ``cls``, followed by every descendant that is."""
    return ([node] if isinstance(node, cls) else []) + list(node.find_all(cls))


class _Replace(NodeTransformer):
    def __init__(self, changes: dict[int, nodes.Node | None]):
        self.changes = changes

    def visit(self, node, *args, **kwargs):
        if id(node) in self.changes:
            return deepcopy(self.changes[id(node)])
        return super().visit(node, *args, **kwargs)


def replaced(tree: nodes.Node, changes: dict[int, nodes.Node | None]) -> nodes.Node:
    """A copy of ``tree`` with the nodes keyed by ``id`` in ``changes`` swapped in."""
    memo: dict = {}
    cloned = deepcopy(tree, memo)
    replacements = {id(memo[old]): new for old, new in changes.items() if old in memo}
    return _Replace(replacements).visit(cloned)


def template_shape(tree: nodes.Node):
    """Compare templates the way Jinja runs them.

    Removing a set can make Jinja merge adjacent output/text nodes.
    """
    class Merge(NodeTransformer):
        def generic_visit(self, node, *args, **kwargs):
            node = super().generic_visit(node, *args, **kwargs)
            for field in node.fields:
                values = getattr(node, field)
                if not isinstance(values, list):
                    continue
                merged = []
                for value in values:
                    if merged and isinstance(value, nodes.Output) and isinstance(merged[-1], nodes.Output):
                        merged[-1].nodes.extend(value.nodes)
                    else:
                        merged.append(value)
                if isinstance(node, nodes.Output):
                    joined = []
                    for value in merged:
                        if joined and isinstance(value, nodes.TemplateData) and isinstance(joined[-1], nodes.TemplateData):
                            joined[-1].data += value.data
                        elif not isinstance(value, nodes.TemplateData) or value.data:
                            joined.append(value)
                    merged = joined
                setattr(node, field, merged)
            if isinstance(node, nodes.Output):
                # A neighboring Output may have just been joined by its parent.
                return node
            for child in node.iter_child_nodes():
                if isinstance(child, nodes.Output):
                    joined = []
                    for value in child.nodes:
                        if joined and isinstance(value, nodes.TemplateData) and isinstance(joined[-1], nodes.TemplateData):
                            joined[-1].data += value.data
                        else:
                            joined.append(value)
                    child.nodes = joined
            return node
    return expression_key(Merge().visit(deepcopy(tree)))


@dataclass(frozen=True)
class _Tag:
    start: int
    end: int
    kind: str
    header: nodes.Node


class TemplateEdits:
    """Locate only complete Jinja tags; untouched code/comments stay byte exact."""
    def __init__(self, source: str, tree: nodes.Template, environment: Environment):
        self.source, self.tree, self.environment = source, tree, environment
        self.edits: list[tuple[int, int, str]] = []
        self.tags: list[_Tag] = []
        self.blocks: list[tuple[int, int]] = []
        stack: list[tuple[str, int]] = []
        tokens = list(environment.lex(source))
        if "".join(value for _, _, value in tokens) != source:
            raise UnsafeEdit()
        start = None
        offset = 0
        for _, kind, value in tokens:
            if kind in {"variable_begin", "block_begin"}:
                start = offset
            offset += len(value)
            if kind not in {"variable_end", "block_end"} or start is None:
                continue
            text = source[start:offset]
            keyword = "output" if kind == "variable_end" else next(
                (value for _, token, value in environment.lex(text) if token == "name"), "",
            )
            opener = keyword in {"if", "for", "macro", "with", "filter", "call", "block", "autoescape"}
            if keyword == "set":
                try:
                    opener = isinstance(environment.parse(text + "{% endset %}").body[0], nodes.AssignBlock)
                except TemplateError:
                    pass
            if opener:
                stack.append((keyword, start))
            elif keyword.startswith("end") and stack and stack[-1][0] == keyword[3:]:
                _, block_start = stack.pop()
                self.blocks.append((block_start, offset))
            try:
                parse_text = text
                if keyword == "elif":
                    parse_text = text.replace("elif", "if", 1) + "{% endif %}"
                elif keyword in {"if", "macro"}:
                    parse_text += "{% end" + keyword + " %}"
                header = environment.parse(parse_text).body[0]
                if keyword in {"output", "set", "if", "elif", "macro"}:
                    self.tags.append(_Tag(start, offset, keyword, header))
            except (TemplateError, IndexError):
                pass
            start = None

    def _tag(self, test) -> _Tag:
        matches = [tag for tag in self.tags if test(tag)]
        if len(matches) != 1:
            raise UnsafeEdit()
        return matches[0]

    def remove(self, assignment: nodes.Assign):
        tag = self._tag(lambda tag: tag.kind == "set" and expression_key(tag.header) == expression_key(assignment))
        self.edits.append((tag.start, tag.end, ""))

    def expressions(self, changes: dict[int, nodes.Node | None]):
        """Rewrite the smallest owning output/assignment/condition tag."""
        for parent in all_nodes(self.tree, (nodes.Output, nodes.Assign, nodes.If)):
            roots = parent.nodes if isinstance(parent, nodes.Output) else [parent.node if isinstance(parent, nodes.Assign) else parent.test]
            for root in roots:
                if isinstance(root, nodes.TemplateData):
                    continue
                changed = replaced(root, changes)
                if expression_key(root) == expression_key(changed):
                    continue
                if isinstance(parent, nodes.Output):
                    tag = self._tag(lambda t: t.kind == "output" and len(t.header.nodes) == 1 and expression_key(t.header.nodes[0]) == expression_key(root))
                    text = "{{ " + expression_source(changed) + " }}"
                elif isinstance(parent, nodes.Assign):
                    tag = self._tag(lambda t: t.kind == "set" and expression_key(t.header) == expression_key(parent))
                    text = "{% set " + expression_source(parent.target) + " = " + expression_source(changed) + " %}"
                else:
                    tag = self._tag(lambda t: t.kind in {"if", "elif"} and expression_key(t.header.test) == expression_key(root))
                    text = "{% " + tag.kind + " " + expression_source(changed) + " %}"
                self.edits.append((tag.start, tag.end, text))

    def macro(self, original: nodes.Macro, revised: nodes.Macro):
        tag = self._tag(lambda t: t.kind == "macro" and t.header.name == original.name)
        defaults = len(revised.args) - len(revised.defaults)
        args = [arg.name + ("=" + expression_source(revised.defaults[i - defaults]) if i >= defaults else "") for i, arg in enumerate(revised.args)]
        self.edits.append((tag.start, tag.end, "{% macro " + revised.name + "(" + ", ".join(args) + ") %}"))

    def finish(self, expected: nodes.Template) -> TemplateEdit:
        edits = sorted(set(self.edits))
        if not edits or any(a[1] > b[0] for a, b in zip(edits, edits[1:])):
            raise UnsafeEdit()
        revised = self.source
        for start, end, text in reversed(edits):
            revised = revised[:start] + text + revised[end:]
        if len(revised) > 4096 or template_shape(self.environment.parse(revised)) != template_shape(expected):
            raise UnsafeEdit()
        # Include enclosing native blocks in the review, rather than showing a
        # detached {{ value }} without the condition that makes the edit useful.
        ranges = set()
        for start, end, _ in edits:
            enclosing = [(a, b) for a, b in self.blocks if a <= start and end <= b]
            ranges.add(min(enclosing, key=lambda span: span[0]) if enclosing else (start, end))
        ranges = sorted(span for span in ranges if not any(other != span and other[0] <= span[0] and span[1] <= other[1] for other in ranges))
        after = []
        for start, end in ranges:
            fragment = self.source[start:end]
            for a, b, text in reversed(edits):
                if start <= a < b <= end:
                    fragment = fragment[:a - start] + text + fragment[b - start:]
            if fragment:
                after.append(fragment)
        return TemplateEdit(
            before="\n".join(self.source[start:end] for start, end in ranges),
            after="\n".join(after),
            output_template=revised,
        )
