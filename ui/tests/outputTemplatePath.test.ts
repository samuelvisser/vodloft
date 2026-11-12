import assert from 'node:assert/strict'
import {test} from 'node:test'

import {
    parseOutputTemplate,
    renderPathOutputTemplate,
} from '../src/components/LocalMediaProfile/outputTemplateFormatting'

const path = (template: string) => renderPathOutputTemplate(parseOutputTemplate(template))

test('hides leading set blocks and keeps the variables they define', () => {
    assert.equal(
        path("{% set output_date = date ~ ' - ' if date %}/downloads/videos/{{ author or source }}/{{ output_date }}{{ title }} [{{ slug }}].ext"),
        '/downloads/videos/{{ author or source }}/{{ output_date }}{{ title }} [{{ slug }}].ext',
    )
})

test('hides if tags and comments but keeps what the if prints', () => {
    assert.equal(
        path("{# movies #}/downloads/movies/{{ movie_title }}{% if media_type != 'movie' %}-{{ media_type }}{% endif %}.ext"),
        '/downloads/movies/{{ movie_title }}-{{ media_type }}.ext',
    )
})

test('shows only the first branch of an if with else', () => {
    assert.equal(
        path('/downloads/shows/{% if season %}Season {{ season }}{% elif year %}{{ year }}{% else %}Specials{% endif %}/{{ title }}.ext'),
        '/downloads/shows/Season {{ season }}/{{ title }}.ext',
    )
})

test('hides set and macro blocks, with whitespace around them', () => {
    assert.equal(
        path('{% set show %}{{ collection_title }}{% endset %}\n{% macro dated(x) %}{{ x }}{% endmacro %}\n/downloads/{{ show }}/{{ dated(title) }}.ext'),
        '/downloads/{{ show }}/{{ dated(title) }}.ext',
    )
})

const simplifiedPath = (template: string) => renderPathOutputTemplate(parseOutputTemplate(template), {simplifyExpressions: true})

test('simplified paths drop filters and format calls', () => {
    assert.equal(
        simplifiedPath('/downloads/{{ collection_title }}/Season {{ "%02d"|format(season_index|int) }}/S{{ "%02d"|format(season_index|int) }}E{{ "%02d"|format(episode_number|int) }} - {{ title }}.ext'),
        '/downloads/{{ collection_title }}/Season {{ season_index }}/S{{ season_index }}E{{ episode_number }} - {{ title }}.ext',
    )
})

test('simplified paths show the first value of if/else and or', () => {
    assert.equal(
        simplifiedPath("/downloads/{{ (meta_collection_folder | as_typed) if meta_collection_folder else (collection_author or 'NA') }}/{{ author or source }}/{{ collection_title | as_typed }}.ext"),
        '/downloads/{{ meta_collection_folder }}/{{ author }}/{{ collection_title }}.ext',
    )
})

test('simplified paths fall back when the first value has no variable', () => {
    assert.equal(simplifiedPath("{{ 'Specials' if special else season.name|default('x') }}"), '{{ season.name }}')
    assert.equal(simplifiedPath("{{ 'NA' }}"), "{{ 'NA' }}")
    assert.equal(simplifiedPath('{{ title if title is defined }}'), '{{ title }}')
})
