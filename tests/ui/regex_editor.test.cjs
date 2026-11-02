// Run with: node --test tests/ui/regex_editor.test.cjs
// Every regex a preset produces opens back in that preset, and the shared
// patterns in tests/fixtures/regex/patterns.json match what the server matches
// (tests/unit/test_regex_check.py runs the same file through the server).
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
    vm.runInNewContext(code, {exports, require: uiRequire})
    return exports
}

const plain = (value) => JSON.parse(JSON.stringify(value))
const model = load('components/RegexEditor/regexModel.ts')
const explain = load('components/RegexEditor/regexExplain.ts')
const cases = JSON.parse(readFileSync(path.join(root, 'tests/fixtures/regex/patterns.json'), 'utf8'))

for (const item of cases) {
    test(`${item.name}: preset and blocks`, () => {
        if (item.blocks) assert.equal(model.buildRegex(item.blocks), item.regex)
        assert.equal(model.inferPreset(item.regex), item.preset)
        if (item.preset !== 'custom') assert.deepEqual(plain(model.parseBlocks(item.regex)), item.blocks)
        else assert.equal(model.parseBlocks(item.regex), null)
    })
    test(`${item.name}: matches in the browser as on the server`, () => {
        const re = new RegExp(item.regex, item.ignoreCase ? 'iu' : 'u')
        for (const text of item.matches) assert.ok(re.test(text), `${item.regex} should match ${text}`)
        for (const text of item.misses) assert.ok(!re.test(text), `${item.regex} should not match ${text}`)
    })
}

test('needless escapes from a pasted regex still open as blocks', () => {
    assert.equal(model.inferPreset('\\b(?:trailer|livestream\\ replay)\\b'), 'anyOf')
})

test('switching tabs keeps the content and Where', () => {
    const contains = model.buildRegex(model.shortcutBlocks('start', {kind: 'text', text: 'Ep.', wholeWords: true}))
    const anyOf = model.switchPreset('anyOf', contains)
    assert.equal(anyOf, '^\\b(?:Ep\\.)')
    assert.equal(model.inferPreset(anyOf), 'anyOf')
    assert.equal(model.switchPreset('contains', anyOf), contains)
    assert.equal(model.presetUnavailable('contains', '\\b(?:a|b)\\b'), 'Has more than one word or phrase')
    assert.equal(model.presetUnavailable('contains', '^Ep\\s*\\d+'), 'Uses a Spaces block')
    assert.match(model.presetUnavailable('pattern', '(?!x)y'), /no block can show/)
})

test('every new block builds a regex that opens back as the same block', () => {
    for (const kind of ['text', 'oneOf', 'number', 'anyText', 'spaces', 'date', 'optional', 'position']) {
        const block = model.newBlock(kind)
        if (block.kind === 'text') block.text = 'x'
        if (block.kind === 'oneOf') block.items = ['a', 'b']
        if (block.kind === 'optional') block.blocks = [{kind: 'text', text: 'y', wholeWords: false}]
        const blocks = kind === 'position' ? [block] : [block]
        assert.deepEqual(plain(model.parseBlocks(model.buildRegex(blocks))), plain(blocks), kind)
    }
    for (const max of [null, 1, 3]) {
        for (const optional of [false, true]) {
            for (const min of [1, 2]) {
                if (max !== null && max < min) continue
                const block = {kind: 'number', min, max, optional}
                assert.deepEqual(plain(model.parseBlocks(model.buildRegex([block]))), [block], JSON.stringify(block))
            }
        }
    }
})

test('the description reads as a sentence', () => {
    assert.equal(
        model.describeBlocks(model.parseBlocks('\\bhighlights\\b'), true),
        'Titles that contain the word “highlights”, in any capitalisation.',
    )
    assert.equal(
        model.describeBlocks(model.parseBlocks('\\b(?:trailer|teaser)\\b'), false, 'description'),
        'Descriptions that contain the word “trailer” or “teaser”, with the capitals exactly as typed.',
    )
})

test('a custom regex is explained part by part and look-arounds are named', () => {
    const result = explain.explainRegex('^(?!.*\\b(?:trailer|teaser)\\b).*\\b(?:Ep|Episode)\\.?\\s*\\d+')
    const texts = result.rows.map((row) => row.text)
    assert.equal(texts[0], 'The start')
    assert.equal(texts[1], 'Only if what follows is not:')
    assert.ok(texts.includes('Any text'))
    assert.ok(texts.includes('Optionally “.”'))
    assert.ok(texts.includes('Any number of spaces, or none'))
    assert.ok(texts.includes('One or more digits'))
    assert.deepEqual(plain(result.unsupported), ['not followed by'])
})

test('tokens cover the regex for colouring', () => {
    const tokens = explain.regexTokens('^Ep\\.\\s*\\d{1,4}')
    assert.deepEqual(plain(tokens.map((token) => token.kind)), ['anchor', 'literal', 'literal', 'escape', 'escape', 'quantifier', 'escape', 'quantifier'])
})
