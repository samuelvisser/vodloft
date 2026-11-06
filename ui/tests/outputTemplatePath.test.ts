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
