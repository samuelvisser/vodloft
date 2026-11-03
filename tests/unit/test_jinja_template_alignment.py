"""align_templates: one template for several that differ in a folder or a name. Jinja only."""
import pytest
from jinja2 import Environment

from jinja_analysis import Alignment, AlignmentFailure, Slot, align_templates

ENV = Environment()
FIELD = dict(variable=lambda key: f"field_{key}", typed=lambda source: f"{source} | typed", default_fallback="name")


def _align(*templates, **options):
    return align_templates(templates, ENV, **{**FIELD, **options})


def _render(template: str, **values) -> str:
    env = Environment()
    env.filters["typed"] = lambda value: value
    return env.from_string(template).render(**values)


def test_identical_templates_share_one_without_slots():
    template = "{% set t = title | upper -%}/d/{{ name }}/{{ t }}.ext"
    result = _align(template, template)
    assert result == Alignment(template, (), ({}, {}))


def test_a_folder_of_plain_text_becomes_a_field_that_falls_back_to_the_default():
    result = _align("/d/First Show/{{ title }}.ext", "/d/Second/{{ title }}.ext")
    assert isinstance(result, Alignment)
    assert result.template == "/d/{{ (field_folder | typed) if field_folder else (name) }}/{{ title }}.ext"
    assert result.slots == (Slot("folder", None),)
    assert result.values == ({"folder": "First Show"}, {"folder": "Second"})
    assert _render(result.template, field_folder="First Show", title="a") == "/d/First Show/a.ext"
    assert _render(result.template, field_folder="", name="Later", title="a") == "/d/Later/a.ext"


def test_an_expression_in_the_slot_is_the_fallback_and_its_input_stores_nothing():
    result = _align("/d/{{ author or 'NA' }}/{{ title }}.ext", "/d/Steven Crowder/{{ title }}.ext")
    assert isinstance(result, Alignment)
    assert result.slots == (Slot("folder", "author or 'NA'"),)
    assert result.values == ({}, {"folder": "Steven Crowder"})
    assert _render(result.template, field_folder="", author="", title="a") == "/d/NA/a.ext"


def test_part_of_the_file_name_is_a_name_slot_cut_at_separators():
    result = _align("/d/x/Show One - {{ title }}.ext", "/d/x/Other Show - {{ title }}.ext")
    assert isinstance(result, Alignment)
    assert [slot.key for slot in result.slots] == ["name"]
    assert result.values == ({"name": "Show One"}, {"name": "Other Show"})


@pytest.mark.parametrize(("templates", "reason"), [
    (("/d/a/{{ title }}.ext", "/d/a/b/{{ title }}.ext"), "different number of folders"),
    (("{% set t = title -%}/d/{{ t }}.ext", "{% set t = name -%}/d/{{ t }}.ext"), "set their variables"),
    (("/d/{{ a }}/x.ext", "/d/{{ b }}/x.ext"), "more than its text"),
    (("/d/x/{{ date }}.ext", "/d/y/ {{ date }}.ext"), "only by a space"),
    (("/d/a/b/c/x.ext", "/d/d/e/f/x.ext"), "More than 2 places"),
    (("/d/a/x.ext", "/d/" + "b" * 300 + "/x.ext"), "longer than"),
])
def test_templates_that_differ_in_more_than_a_few_plain_texts_stay_apart(templates, reason):
    result = _align(*templates)
    assert isinstance(result, AlignmentFailure)
    assert reason in result.reason


def test_the_slot_limit_can_be_lowered():
    result = _align("/d/a/b/x.ext", "/d/c/d/x.ext", max_slots=1)
    assert isinstance(result, AlignmentFailure)
    assert isinstance(_align("/d/a/b/x.ext", "/d/c/d/x.ext"), Alignment)
