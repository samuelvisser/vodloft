"""The shared printer, template edits and filter table of the jinja_analysis package.

These tests only use jinja2 and the package itself.
"""
from jinja2 import Environment, nodes
import pytest

from jinja_analysis.expressions import expression_key
from jinja_analysis.filters import PURE_FILTERS, STRING_FILTERS, VOLATILE_FILTERS, filter_result
from jinja_analysis.source import TemplateEdits, UnsafeEdit, expression_source


ENVIRONMENT = Environment()


def _expression(source: str) -> nodes.Expr:
    return ENVIRONMENT.parse("{{ " + source + " }}").body[0].nodes[0]


@pytest.mark.parametrize(("source", "printed"), [
    ("title", "title"),
    ("'%03d' | format(episode_index | int)", "'%03d' | format(episode_index | int)"),
    ("a ~ ' - ' ~ b", "a ~ ' - ' ~ b"),
    ("(a ~ b) | upper", "(a ~ b) | upper"),
    ("not is_extra", "not is_extra"),
    ("not (a and b)", "not (a and b)"),
    ("a or b and c", "a or b and c"),
    ("(a or b) and c", "(a or b) and c"),
    ("uploader ~ ' - ' if uploader", "uploader ~ ' - ' if uploader"),
    ("(x if y else z) ~ w", "(x if y else z) ~ w"),
    ("a - (b - c)", "a - (b - c)"),
    ("(a - b) - c", "a - b - c"),
    ("-(x | abs)", "-(x | abs)"),
    ("-x | abs", "-x | abs"),
    ("a + b * c", "a + b * c"),
    ("(a + b) * c", "(a + b) * c"),
    ("a ~ b + c", "a ~ b + c"),
    ("a ~ (b + c)", "a ~ (b + c)"),
    ("x is divisibleby(3)", "x is divisibleby(3)"),
    ("date | strftime('%m%d')", "date | strftime('%m%d')"),
    ("values[key].name", "values[key].name"),
    ("f(a, b=1)", "f(a, b=1)"),
    ("[1, 'two', none, true]", "[1, 'two', none, true]"),
    ("(single,)", "(single,)"),
    ("{'a': 1}", "{'a': 1}"),
    ("year in [2024, 2025]", "year in [2024, 2025]"),
    ("'day' | custom_index(per=date, start=99, step=-1)", "'day' | custom_index(per=date, start=99, step=-1)"),
])
def test_printed_expressions_parse_back_to_the_same_tree_with_only_needed_brackets(source, printed):
    expression = _expression(source)

    assert expression_source(expression) == printed
    assert expression_key(_expression(printed)) == expression_key(expression)


def test_printer_refuses_what_is_not_a_plain_expression():
    with pytest.raises(UnsafeEdit):
        expression_source(_expression("items[1:2]"))
    with pytest.raises(UnsafeEdit):
        expression_source(_expression("f(*args)"))


def test_template_edits_change_only_the_edited_tag():
    source = "{# keep #}{%- set a = title -%}/x/{{  a | upper  }}/{{ b }}.ext"
    tree = ENVIRONMENT.parse(source)
    output = tree.body[-1]
    old = output.nodes[1]
    new = nodes.Filter(nodes.Name("a", "load"), "lower", [], [], None, None)
    expected = ENVIRONMENT.parse(source.replace("{{  a | upper  }}", "{{ a | lower }}"))

    edits = TemplateEdits(source, tree, ENVIRONMENT)
    edits.expressions({id(old): new})
    result = edits.finish(expected)

    assert result.output_template == "{# keep #}{%- set a = title -%}/x/{{ a | lower }}/{{ b }}.ext"
    assert result.before == "{{  a | upper  }}"
    assert result.after == "{{ a | lower }}"


def test_template_edits_refuse_an_edit_that_does_not_give_the_expected_template():
    source = "{{ a }}"
    tree = ENVIRONMENT.parse(source)
    edits = TemplateEdits(source, tree, ENVIRONMENT)
    edits.expressions({id(tree.body[0].nodes[0]): nodes.Name("b", "load")})

    with pytest.raises(UnsafeEdit):
        edits.finish(ENVIRONMENT.parse("{{ c }}"))


def test_one_filter_table_answers_purity_and_result_types():
    assert {"strftime", "regex_replace", "regex_groups"} <= PURE_FILTERS
    assert VOLATILE_FILTERS == {"custom_index", "random"}
    assert not PURE_FILTERS & VOLATILE_FILTERS
    assert {"strftime", "regex_replace", "format", "upper"} <= STRING_FILTERS
    assert filter_result("upper", "str", has_arguments=False) == "str"
    assert filter_result("upper", "int", has_arguments=False) is None
    assert filter_result("abs", "int", has_arguments=False) == "int"
    assert filter_result("string", "int", has_arguments=False) == "str"
    assert filter_result("replace", "str", has_arguments=True) is None
    assert filter_result("random", "str", has_arguments=False) is None


def test_the_package_imports_only_jinja2_and_itself():
    import ast
    from pathlib import Path

    import jinja_analysis

    allowed = {"jinja2", "jinja_analysis", "__future__", "collections", "copy", "dataclasses", "enum",
               "functools", "itertools", "math", "pathlib", "re", "typing"}
    for path in Path(jinja_analysis.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in allowed, f"{path.name} imports {name}"
