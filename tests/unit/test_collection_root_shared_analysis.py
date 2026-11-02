from __future__ import annotations

import re

from jinja2.sandbox import ImmutableSandboxedEnvironment
import pytest

from backend.utils.collection_media_directory import infer_collection_media_directory


def _root(template, **kwargs):
    values = dict(collection='my-collection', collection_title='My Show', meta_collection_folder='Custom Collection',
                  season_name='Introduction', season_number='1', year='2026', date='2026-09-27',
                  episode_type='ep', title='First', episode='first', episode_title='First')
    environment = ImmutableSandboxedEnvironment()
    environment.globals.clear()
    environment.finalize = lambda value: ''.join(c for c in str(value or '').replace('/', '_').replace('\\', '_') if ord(c) >= 32)
    environment.filters['custom_index'] = lambda _key: pytest.fail('Must not calculate an index')
    return infer_collection_media_directory(template, values, environment=environment,
                                     sanitize_component=lambda value: re.sub(r'[<>:"\\|?*]', '_', value), **kwargs)


@pytest.mark.parametrize(('template', 'expected'), [
    ('/downloads/TV/{{ collection_title }}/Season {{ season_number }}/{{ title }}.ext', '/downloads/TV/My Show'),
    ('/downloads/Podcasts/{{ collection_title }}/{{ date }} - {{ title }}.ext', '/downloads/Podcasts/My Show'),
    ('/downloads/{{ collection }}/{{ year }}/{{ title }}.ext', '/downloads/my-collection'),
    ('/downloads/{{ collection }}/{{ season_name }}/{{ title }}.ext', '/downloads/my-collection'),
    ('/downloads/{{ collection }}/Season 01/{{ title }}.ext', '/downloads/my-collection'),
    ('/downloads/{{ collection }}/S.01/{{ title }}.ext', '/downloads/my-collection'),
    ('/downloads/{{ collection }}/Extras/{{ title }}.ext', '/downloads/my-collection'),
    ('/downloads/{{ collection }}/audio/{{ title }}.ext', '/downloads/my-collection/audio'),
    ('/downloads/TV/My Show/Season 01/{{ title }}.ext', '/downloads/TV/My Show'),
    ('/downloads/{{ meta_collection_folder }}/{{ title }}.ext', '/downloads/Custom Collection'),
    ('{% set name = collection_title|lower %}/downloads/{{ name }}/{{ title }}.ext', '/downloads/my show'),
    ('{% set name %}{{ collection_title|upper }}{% endset %}/downloads/{{ name }}/{{ title }}.ext', '/downloads/MY SHOW'),
    ('{% macro folder(value) %}{{ value|upper }}{% endmacro %}/downloads/{{ folder(collection) }}/{{ title }}.ext', '/downloads/MY-COLLECTION'),
    ('{% with name = collection_title %}/downloads/{{ name }}/{{ title }}.ext{% endwith %}', '/downloads/My Show'),
    ('/downloads/{{ collection }}/{% if year %}{{ year }}/{% endif %}{{ title }}.ext', '/downloads/my-collection'),
    ("/downloads/{{ collection }}/{% if episode_type == 'aux' %}Extras/{% else %}Episodes/{% endif %}{{ title }}.ext", '/downloads/my-collection'),
    ("{% if episode_type == 'aux' %}{% set section='Extras' %}{% else %}{% set section='Episodes' %}{% endif %}/downloads/{{ collection }}/{{ section }}/{{ title }}.ext", '/downloads/my-collection'),
    ("{% set section = 'order'|custom_index %}/downloads/{{ collection }}/{{ section }}/{{ title }}.ext", '/downloads/my-collection'),
    ("/downloads/{{ collection }}/{{ 'order'|custom_index }}/{{ title }}.ext", '/downloads/my-collection'),
    ("{% if episode_type == 'aux' %}/downloads/Extras/{{ collection }}/{% else %}/downloads/Shows/{{ collection }}/{% endif %}{{ title }}.ext", None),
    ('/downloads/{{ year }}/{{ collection }}/{{ title }}.ext', None),
    ('/downloads/TV/{{ title }}.ext', None),
    ('/downloads/{{ collection_title|random }}/{{ title }}.ext', None),
    ('/downloads/../{{ collection }}/{{ title }}.ext', None),
    ('/outside/{{ collection }}/{{ title }}.ext', None),
    ("{% include 'external' %}", None),
    ('/downloads/{{ collection }}/{{ 1 / 0 }}/{{ title }}.ext', None),
])
def test_collection_directory_policy_on_shared_analysis(template, expected):
    result = _root(template)
    assert result.path == expected
    assert bool(result.reason) is (expected is None)


def test_known_literal_season_names():
    assert _root('/downloads/{{ collection }}/Introduction/{{ title }}.ext', season_names=('Introduction',)).path == '/downloads/my-collection'


def test_filename_only_complexity_does_not_limit_a_clear_collection_root():
    helpers = '{% if year %}{% set label=title %}{% else %}{% set label=episode %}{% endif %}' * 12
    assert _root(helpers + '/downloads/{{ collection }}/{{ label }}.ext').path == '/downloads/my-collection'
    assert _root('/downloads/{{ collection }}/' + '{% if year %}a{% else %}b{% endif %}' * 12 + '{{ title }}.ext').path == '/downloads/my-collection'


def test_correlated_directory_branches_do_not_invent_impossible_layouts():
    template = '/downloads/{{ collection }}/{% if year %}A/{% else %}B/{% endif %}{% if not year %}X/{% endif %}{{title}}.ext'
    assert _root(template).path == '/downloads/my-collection'
