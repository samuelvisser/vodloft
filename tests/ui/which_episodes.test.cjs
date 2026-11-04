// Run with: node --test tests/ui/which_episodes.test.cjs
// The sentences Which episodes shows for its lines.
const {test} = require('node:test')
const assert = require('node:assert/strict')
const {readFileSync} = require('node:fs')
const {createRequire} = require('node:module')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../..')
const uiRequire = createRequire(path.join(root, 'ui/package.json'))
const ts = uiRequire('typescript')

function load(relativePath) {
    const source = readFileSync(path.join(root, 'ui/src', relativePath), 'utf8')
    const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText
    const exports = {}
    const localRequire = (name) => name.startsWith('.')
        ? load(path.join(path.dirname(relativePath), `${name}.ts`))
        : uiRequire(name)
    vm.runInNewContext(code, {exports, require: localRequire})
    return exports
}

const text = load('components/DownloadProfile/whichEpisodesText.ts')
const sentence = (parts) => parts.map((part) => part.code ? `[${part.text}]` : part.text).join('')

test('a title filter says what it matches and shows its regex', () => {
    const parts = text.filterSentence({action: 'skip', field: 'title', pattern: '(?i)\\b(?:trailer|teaser)\\b'})
    assert.equal(sentence(parts), 'Skip if the title contains the word “trailer” or “teaser”, in any capitalisation[\\b(?:trailer|teaser)\\b]')
    assert.equal(text.plainText(parts), 'Skip if the title contains the word “trailer” or “teaser”, in any capitalisation')
})

test('a regex no block can show says it matches', () => {
    const parts = text.filterSentence({action: 'only', field: 'description', pattern: '(?<=x)y'})
    assert.equal(sentence(parts), 'Only download if the description matches[(?<=x)y]')
})

test('a duration filter names the length in words', () => {
    assert.equal(
        text.plainText(text.filterSentence({action: 'skip', field: 'duration', durationOperator: 'longer', durationSeconds: 5400})),
        'Skip if the duration is longer than 1 hour 30 minutes',
    )
    assert.equal(text.formatDuration(120), '2 minutes')
})

test('a season filter names its seasons and upcoming ones', () => {
    const names = {s1: 'Season 1', s2: 'Season 2'}
    assert.equal(
        text.plainText(text.filterSentence({action: 'keep', field: 'seasons', seasonSlugs: ['s1', 's2']}, undefined, (slug) => names[slug])),
        'Keep if the season is Season 1 or Season 2',
    )
    assert.equal(
        text.plainText(text.filterSentence({action: 'only', field: 'seasons', seasonSlugs: ['s2'], includeUpcoming: true}, undefined, (slug) => names[slug])),
        'Only download if the season is Season 2 or upcoming seasons',
    )
    assert.equal(text.filterComplete({action: 'skip', field: 'seasons', seasonSlugs: []}), false)
    assert.equal(text.filterComplete({action: 'only', field: 'seasons', seasonSlugs: [], includeUpcoming: true}), true)
})

test('a date line says whether it deletes', () => {
    const today = new Date(2026, 10, 2)
    assert.equal(sentence(text.filterSentence({action: 'only', field: 'published', count: 5}, undefined, undefined, true, today)), 'Only download the latest 5 episodes, and delete older ones')
    assert.equal(sentence(text.filterSentence({action: 'keep', field: 'published', count: 5}, undefined, undefined, true, today)), 'Keep the latest 5 episodes')
    assert.match(
        sentence(text.filterSentence({action: 'only', field: 'downloaded', days: 30}, undefined, undefined, true, today)),
        /^Only download episodes published in the last 30 days, and delete them 30 days after downloading$/,
    )
    assert.equal(sentence(text.filterSentence({action: 'keep', field: 'downloaded', days: 30}, undefined, undefined, true, today)), 'Keep downloads for 30 days after downloading')
    assert.match(sentence(text.filterSentence({action: 'only', field: 'published', startingFrom: '2026-01-10'}, undefined, undefined, true, today)), /^Only download episodes published since /)
})

const filters = load('components/DownloadProfile/episodeFilters.ts')

test('a new filter goes where its kind belongs', () => {
    const list = [{field: 'seasons'}, {field: 'types'}, {field: 'title'}, {field: 'published'}]
    assert.equal(filters.insertIndex(list, 'seasons'), 1)
    assert.equal(filters.insertIndex(list, 'types'), 2)
    assert.equal(filters.insertIndex(list, 'duration'), 3)
    assert.equal(filters.insertIndex(list, 'downloaded'), 4)
    assert.equal(filters.insertIndex([], 'title'), 0)
})

test('a leading (?i) is shown as any capitalisation', () => {
    assert.deepEqual({...filters.splitIgnoreCase('(?i)news')}, {pattern: 'news', ignoreCase: true})
    assert.equal(filters.joinIgnoreCase({pattern: 'news', ignoreCase: false}), 'news')
})

test('the episode types a list downloads', () => {
    assert.equal(filters.downloadedEpisodeTypes([{action: 'only', field: 'published', count: 5}]), null)
    assert.deepEqual([...filters.downloadedEpisodeTypes([
        {action: 'only', field: 'types', episodeTypes: ['ep', 'aux']},
        {action: 'skip', field: 'types', episodeTypes: ['aux']},
    ])], ['ep'])
})
