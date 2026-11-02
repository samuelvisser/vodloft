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

test('a title rule says what it matches and shows its regex', () => {
    const parts = text.ruleSentence({action: 'skip', field: 'title', pattern: '\\b(?:trailer|teaser)\\b', ignoreCase: true})
    assert.equal(sentence(parts), 'Skip if the title contains the word “trailer” or “teaser”, in any capitalisation[\\b(?:trailer|teaser)\\b]')
    assert.equal(text.plainText(parts), 'Skip if the title contains the word “trailer” or “teaser”, in any capitalisation')
})

test('a regex no block can show says it matches', () => {
    const parts = text.ruleSentence({action: 'only', field: 'description', pattern: '(?<=x)y', ignoreCase: false})
    assert.equal(sentence(parts), 'Only download if the description matches[(?<=x)y]')
})

test('a duration rule names the length in words', () => {
    assert.equal(
        text.plainText(text.ruleSentence({action: 'skip', field: 'duration', durationOperator: 'longer', durationSeconds: 5400})),
        'Skip if the duration is longer than 1 hour 30 minutes',
    )
    assert.equal(text.formatDuration(120), '2 minutes')
})

test('the built-in lines read as one sentence', () => {
    assert.equal(sentence(text.typesSentence(['Video', 'Livestream'])), 'Download Video and Livestream episodes')
    assert.equal(sentence(text.seasonsSentence(['Season 1'], true)), 'from Season 1 and upcoming seasons')
    const today = new Date(2026, 10, 2)
    const window = {downloadDaysInPast: 30, downloadEpisodeCount: 0, downloadStartingFrom: null, deleteOlderEpisodes: true, retentionFrom: 'downloaded'}
    assert.match(sentence(text.dateSentence(window, today)), /^published in the last 30 days \(since .+\), and delete them 30 days after downloading$/)
    assert.equal(sentence(text.dateSentence({...window, downloadDaysInPast: 0, downloadEpisodeCount: 5}, today)), 'only the latest 5 episodes, and delete older ones')
    assert.equal(sentence(text.dateSentence({...window, downloadDaysInPast: 0}, today)), 'published at any time')
})
