"""Bounded, source-preserving Jinja refactors for the editor's index advisory.

These are optional source edits, never a rendering transform. Only move a
single-use, closed, total expression into an existing guarded use. Reparse every
edit and compare its AST with the intended edit, including all untouched code.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re

from jinja2 import Environment, TemplateError, nodes

from .expressions import expression_key
from .filters import filter_result
from .source import TemplateEdit, TemplateEdits, UnsafeEdit, all_nodes, expression_source, replaced


def _index(node: nodes.Node, key: str) -> bool:
    return (
        isinstance(node, nodes.Filter) and node.name == "custom_index"
        and isinstance(node.node, nodes.Const) and node.node.value == key
        and not (node.args or node.kwargs or node.dyn_args or node.dyn_kwargs)
    )


def _loads(node: nodes.Node, name: str) -> list[nodes.Name]:
    return [item for item in all_nodes(node, nodes.Name) if item.ctx == "load" and item.name == name]


def _movable(node: nodes.Node, key: str) -> str | None:
    """Known-total closed computations only; never execute a user's filter.

    No free variables means no closure/rebinding/evaluation-timing assumptions.
    Numeric format strings have a deliberately small, total whitelist.
    """
    if _index(node, key):
        return "int"
    if isinstance(node, nodes.Const):
        return "str" if isinstance(node.value, str) else "int" if type(node.value) is int else None
    if isinstance(node, nodes.Concat) and all(_movable(item, key) for item in node.nodes):
        return "str"
    if isinstance(node, nodes.Filter) and not (node.kwargs or node.dyn_args or node.dyn_kwargs):
        value_type = _movable(node.node, key)
        result = filter_result(node.name, value_type, has_arguments=bool(node.args))
        if result is not None:
            return result
        if node.name == "format" and isinstance(node.node, nodes.Const) and isinstance(node.node.value, str):
            # Literals and %% plus exactly one bounded integer/string conversion.
            pattern = node.node.value
            conversions = re.findall(r"%(?:0?[1-9][0-9]?)?[ds]", pattern.replace("%%", ""))
            rest = re.sub(r"%(?:0?[1-9][0-9]?)?[ds]", "", pattern.replace("%%", ""))
            if len(conversions) == len(node.args) == 1 and "%" not in rest:
                kind = _movable(node.args[0], key)
                if kind and (conversions[0].endswith("s") or kind == "int"):
                    return "str"
    return None


class _Context:
    def __init__(self, tree: nodes.Template):
        self.tree = tree
        self.parents = {}
        self.writes = Counter(n.name for n in tree.find_all(nodes.Name) if n.ctx in {"store", "param"})
        self.bindings = {n.target.name: n.node for n in tree.body if isinstance(n, nodes.Assign) and isinstance(n.target, nodes.Name)}
        counts = Counter(n.name for n in tree.find_all(nodes.Macro))
        self.macros = {n.name: n for n in tree.body if isinstance(n, nodes.Macro) and counts[n.name] == 1}
        def visit(node):
            if len(self.parents) > 2048:
                raise UnsafeEdit()
            for field in node.fields:
                value = getattr(node, field)
                children = enumerate(value) if isinstance(value, list) else [(None, value)]
                for index, child in children:
                    if isinstance(child, nodes.Node):
                        self.parents[id(child)] = (node, field, index)
                        visit(child)
        visit(tree)

    def invocation(self, macro: nodes.Macro) -> tuple[nodes.Call, dict[str, nodes.Expr]]:
        if self.macros.get(macro.name) is not macro:
            raise UnsafeEdit()
        uses = _loads(self.tree, macro.name)
        if self.writes[macro.name] or len(uses) != 1:
            raise UnsafeEdit()
        call, field, _ = self.parents[id(uses[0])]
        if not isinstance(call, nodes.Call) or field != "node" or call.dyn_args or call.dyn_kwargs:
            raise UnsafeEdit()
        if len(call.args) > len(macro.args) or len({item.key for item in call.kwargs}) != len(call.kwargs):
            raise UnsafeEdit()
        names = [arg.name for arg in macro.args]
        values = dict(zip(names[-len(macro.defaults):], macro.defaults)) if macro.defaults else {}
        values.update(zip(names, call.args))
        for item in call.kwargs:
            if item.key not in names or item.key in names[:len(call.args)]:
                raise UnsafeEdit()
            values[item.key] = item.value
        return call, values

    def stable(self, node: nodes.Node, parameters: dict[str, nodes.Expr], seen=frozenset()) -> bool:
        if len(seen) > 64:
            return False
        if isinstance(node, nodes.Name):
            if node.name in seen:
                return False
            value = parameters.get(node.name)
            if value is not None:
                return self.stable(value, {}, seen | {node.name})
            if self.writes[node.name] > 1:
                return False
            value = self.bindings.get(node.name)
            if value is not None:
                return self.stable(value, parameters, seen | {node.name})
            return self.writes[node.name] == 0
        if isinstance(node, nodes.Call):
            return False
        if isinstance(node, nodes.Filter) and node.name not in {
            "abs", "capitalize", "float", "format", "int", "length", "lower", "replace",
            "round", "string", "title", "trim", "upper", "regex_replace", "regex_search",
        }:
            return False
        return all(self.stable(child, parameters, seen) for child in node.iter_child_nodes())

    def top_level(self, node: nodes.Node) -> nodes.Node:
        while id(node) in self.parents and self.parents[id(node)][0] is not self.tree:
            node = self.parents[id(node)][0]
        return node

    def guarded(self, target: nodes.Node, stack=frozenset()) -> bool:
        guards: list[nodes.Node] = []
        parameters: dict[str, nodes.Expr] = {}
        nested_guard = False
        node = target
        while id(node) in self.parents:
            parent, field, position = self.parents[id(node)]
            if isinstance(parent, nodes.If):
                if field == "body":
                    guards.append(parent.test)
                elif field in {"else_", "elif_"}:
                    guards.append(parent.test)
                    if field == "elif_":
                        guards.extend(item.test for item in parent.elif_[:position])
                    if field == "else_":
                        guards.extend(item.test for item in parent.elif_)
            elif isinstance(parent, nodes.CondExpr) and field in {"expr1", "expr2"}:
                guards.append(parent.test)
            elif isinstance(parent, (nodes.And, nodes.Or)) and field == "right":
                guards.append(parent.left)
            elif isinstance(parent, (nodes.Assign, nodes.AssignBlock)):
                if not isinstance(parent.target, nodes.Name) or not _loads(self.tree, parent.target.name):
                    raise UnsafeEdit()  # Do not infer intent from a dead value.
            elif isinstance(parent, nodes.Macro):
                if parent.name in stack:
                    raise UnsafeEdit()
                call, parameters = self.invocation(parent)
                nested_guard = self.guarded(call, stack | {parent.name})
            elif isinstance(parent, (nodes.For, nodes.CallBlock, nodes.With)):
                # Their scoping/evaluation counts are outside the bounded rewrite.
                raise UnsafeEdit()
            node = parent
        return (nested_guard or bool(guards)) and all(self.stable(guard, parameters) for guard in guards)


def _single_assignment(source, tree, key, environment, context):
    calls = [n for n in tree.find_all(nodes.Filter) if _index(n, key)]
    if len(calls) != 1:
        return None
    assignments = [n for n in tree.body if isinstance(n, nodes.Assign) and isinstance(n.target, nodes.Name)]
    current = next((n for n in assignments if calls[0] in all_nodes(n.node, nodes.Filter)), None)
    if current is None or not _movable(current.node, key):
        return None
    replacement = deepcopy(current.node)
    removed = []
    for _ in range(32):
        name = current.target.name
        if context.writes[name] != 1 or name in context.macros:
            return None
        uses = _loads(tree, name)
        if len(uses) != 1:
            return None
        removed.append(current)
        use = uses[0]
        consumer = next((n for n in assignments if use in all_nodes(n.node, nodes.Name)), None)
        if consumer is not None:
            if tree.body.index(consumer) <= tree.body.index(current):
                return None
            combined = replaced(consumer.node, {id(use): replacement})
            if _movable(combined, key):
                current, replacement = consumer, combined
                continue
        if tree.body.index(context.top_level(use)) <= tree.body.index(current) or not context.guarded(use):
            return None
        # Never move a global declaration into a macro defined before the binding.
        enclosing = use
        while id(enclosing) in context.parents:
            enclosing = context.parents[id(enclosing)][0]
            if isinstance(enclosing, nodes.Macro) and tree.body.index(enclosing) < tree.body.index(current):
                return None
        edits = TemplateEdits(source, tree, environment)
        changes = {id(use): replacement}
        edits.expressions(changes)
        for declaration in removed:
            edits.remove(declaration)
            changes[id(declaration)] = None
        return edits.finish(replaced(tree, changes))
    return None


def _macro_argument(source, tree, key, environment, context):
    for macro in context.macros.values():
        try:
            call, parameters = context.invocation(macro)
        except UnsafeEdit:
            continue
        if macro.defaults or any(_loads(macro, name) for name in ("caller", "varargs", "kwargs")):
            continue
        for index, parameter in enumerate(macro.args):
            value = parameters.get(parameter.name)
            if value is None:
                continue
            removed = []
            # A single-use closed alias passed at the call site is equally safe
            # to specialize. Do not substitute episode inputs or other arguments.
            for _ in range(32):
                names = list(value.find_all(nodes.Name)) if not isinstance(value, nodes.Name) else [value]
                if not names:
                    break
                replacements = {}
                for name in names:
                    binding = next((n for n in tree.body if isinstance(n, nodes.Assign) and isinstance(n.target, nodes.Name) and n.target.name == name.name), None)
                    if binding is None or context.writes[name.name] != 1 or len(_loads(tree, name.name)) != 1:
                        break
                    if tree.body.index(binding) >= tree.body.index(context.top_level(call)):
                        break
                    replacements[id(name)] = binding.node
                    removed.append(binding)
                if len(replacements) != len(names):
                    break
                value = replaced(value, replacements)
            if not any(_index(n, key) for n in all_nodes(value, nodes.Filter)) or not _movable(value, key):
                continue
            uses = _loads(tree, parameter.name)
            if context.writes[parameter.name] != 1 or len(uses) != 1 or not context.guarded(uses[0]):
                continue
            revised_macro = deepcopy(macro)
            revised_macro.args.pop(index)
            revised_macro.body = replaced(nodes.Template(macro.body), {id(uses[0]): value}).body
            revised_call = deepcopy(call)
            if index < len(call.args):
                revised_call.args.pop(index)
            else:
                revised_call.kwargs = [item for item in revised_call.kwargs if item.key != parameter.name]
            edits = TemplateEdits(source, tree, environment)
            edits.expressions({id(uses[0]): value, id(call): revised_call})
            edits.macro(macro, revised_macro)
            changes = {id(macro): revised_macro, id(call): revised_call}
            for declaration in removed:
                edits.remove(declaration)
                changes[id(declaration)] = None
            return edits.finish(replaced(tree, changes))
    return None


def _container_lookup(source, tree, key, environment, context):
    """Make literal-table selection lazy without dropping other computations.

    Named tables keep every non-index entry at its original evaluation site.
    Only the index slot becomes a placeholder, and all reads of that slot are
    rewritten. Inline tables are limited to constants/already-bound scalar reads.
    """
    for container in tree.find_all((nodes.List, nodes.Tuple, nodes.Dict)):
        if not any(_index(n, key) for n in container.find_all(nodes.Filter)):
            continue
        if isinstance(container, nodes.Dict):
            if not all(isinstance(pair.key, nodes.Const) and type(pair.key.value) in {str, int, bool} for pair in container.items):
                continue
            entries = [(pair.key.value, pair.value) for pair in container.items]
            if len({k for k, _ in entries}) != len(entries):
                continue
            values = dict(entries)
        else:
            values = dict(enumerate(container.items))
        indexed = {k for k, value in values.items() if any(_index(n, key) for n in all_nodes(value, nodes.Filter))}
        if len(indexed) != 1 or not all(_movable(values[k], key) for k in indexed):
            continue
        parent, field, _ = context.parents[id(container)]
        declaration = parent if isinstance(parent, nodes.Assign) and parent in tree.body and field == "node" else None
        if declaration is not None:
            if not isinstance(declaration.target, nodes.Name) or context.writes[declaration.target.name] != 1:
                continue
            references = _loads(tree, declaration.target.name)
            lookups = []
            for reference in references:
                lookup, role, _ = context.parents[id(reference)]
                if not isinstance(lookup, nodes.Getitem) or role != "node":
                    break
                lookups.append(lookup)
            if len(lookups) != len(references) or not lookups:
                continue
            if any(tree.body.index(context.top_level(lookup)) <= tree.body.index(declaration) for lookup in lookups):
                continue
            # A mutable/aliased container is never specialized; every observer
            # must be one of these explicitly checked literal-key selections.
            if any(any(isinstance(n, nodes.Macro) for n in _ancestors(context, lookup)) for lookup in lookups):
                continue
        elif isinstance(parent, nodes.Getitem) and field == "node":
            lookups = [parent]
            def scalar_read(value):
                if _movable(value, key):
                    return True
                if isinstance(value, nodes.Name):
                    if context.writes[value.name] == 0:
                        return True  # VODLoft supplies media input values as text.
                    binding = next((n for n in tree.body if isinstance(n, nodes.Assign) and isinstance(n.target, nodes.Name) and n.target.name == value.name), None)
                    return binding is not None and context.writes[value.name] == 1 and tree.body.index(binding) < tree.body.index(context.top_level(container))
                return isinstance(value, nodes.Concat) and all(scalar_read(n) for n in value.nodes)
            if not all(scalar_read(value) for value in values.values()):
                continue
        else:
            continue

        def boolean(selector, seen=frozenset()):
            if isinstance(selector, (nodes.Compare, nodes.Not, nodes.Test)):
                return True
            if isinstance(selector, nodes.Const):
                return type(selector.value) is bool
            if isinstance(selector, (nodes.And, nodes.Or)):
                return boolean(selector.left, seen) and boolean(selector.right, seen)
            if isinstance(selector, nodes.Name) and selector.name not in seen and context.writes[selector.name] == 1:
                value = context.bindings.get(selector.name)
                return value is not None and boolean(value, seen | {selector.name})
            return False

        def select(selector, lookup):
            if isinstance(selector, nodes.Const) and type(selector.value) in {str, int, bool}:
                if not isinstance(container, nodes.Dict) and type(selector.value) is not int:
                    raise UnsafeEdit()
                if selector.value not in values:
                    raise UnsafeEdit()
                if declaration is not None and selector.value not in indexed:
                    return nodes.Getitem(deepcopy(lookup.node), deepcopy(selector), "load")
                return deepcopy(values[selector.value])
            if isinstance(selector, nodes.CondExpr) and selector.expr2 is not None and context.stable(selector.test, {}):
                return nodes.CondExpr(deepcopy(selector.test), select(selector.expr1, lookup), select(selector.expr2, lookup))
            if isinstance(container, nodes.Dict) and set(values) == {True, False} and boolean(selector) and context.stable(selector, {}):
                return nodes.CondExpr(deepcopy(selector), select(nodes.Const(True), lookup), select(nodes.Const(False), lookup))
            raise UnsafeEdit()

        changes = {id(lookup): select(lookup.arg, lookup) for lookup in lookups}
        if declaration is not None:
            changes.update({id(values[k]): nodes.Const(None) for k in indexed})
        expected = replaced(tree, changes)
        checked = _Context(expected)
        index_calls = [n for n in expected.find_all(nodes.Filter) if _index(n, key)]
        if len(index_calls) != 1 or not checked.guarded(index_calls[0]):
            continue
        edits = TemplateEdits(source, tree, environment)
        edits.expressions(changes)
        return edits.finish(expected)
    return None


def _ancestors(context: _Context, node: nodes.Node):
    while id(node) in context.parents:
        node = context.parents[id(node)][0]
        yield node


def suggest_guarded_index(source: str, tree: nodes.Template, key: str, environment: Environment) -> TemplateEdit | None:
    """Try independent bounded proofs. Uncertainty is advice withheld, not an error."""
    if len([node for node in tree.find_all(nodes.Filter) if _index(node, key)]) != 1:
        return None
    if any(tree.find_all((nodes.Import, nodes.FromImport, nodes.Include, nodes.Extends))):
        return None
    try:
        context = _Context(tree)
    except UnsafeEdit:
        return None
    for strategy in (_single_assignment, _macro_argument, _container_lookup):
        try:
            result = strategy(source, tree, key, environment, context)
            if result is not None:
                return result
        except (UnsafeEdit, TemplateError, RecursionError, KeyError, TypeError, ValueError):
            continue
    return None
