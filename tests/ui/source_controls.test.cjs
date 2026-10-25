// Run with: node --test tests/ui/source_controls.test.cjs
// A stub Source with no Features must not get any Daily Wire control.
const {test} = require('node:test')
const assert = require('node:assert/strict')
const {readFileSync} = require('node:fs')
const {createRequire} = require('node:module')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../..')
const uiRequire = createRequire(path.join(root, 'ui/package.json'))
const ts = uiRequire('typescript')

function load(relativePath, modules = {}) {
    const source = readFileSync(path.join(root, 'ui/src', relativePath), 'utf8')
    const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText
    const exports = {}
    vm.runInNewContext(code, {exports, require: (name) => modules[name] ?? uiRequire(name)})
    return exports
}

// Objects made inside the VM have their own prototypes; compare them as plain data.
const plain = (value) => JSON.parse(JSON.stringify(value))

const sourceSchemas = load('types/schemas/source.ts')
const {sourceControls, linkTarget} = load('lib/sourceControls.ts', {'../types/schemas/source': sourceSchemas})

const stubItem = {sourceKey: 'stub', sourceFeatures: []}
const dailyWireItem = {
    sourceKey: 'dailywire',
    sourceFeatures: ['browse', 'live_episodes', 'login', 'membership_levels', 'movie_extras', 'movies', 'rss_streaming', 'shows'],
}

test('a Source without Features gets none of the Daily Wire controls', () => {
    assert.deepEqual(plain(sourceControls(stubItem)), {
        membershipLevels: false,
        liveEpisodes: false,
        countdownDownloads: false,
        rssStreaming: false,
        movieExtras: false,
        metadataRefresh: true,
    })
})

test('a Source that lists its episodes has no metadata refresh', () => {
    assert.equal(sourceControls({sourceKey: 'ytdlp', sourceFeatures: ['shows', 'episode_lists']}).metadataRefresh, false)
})

test('Daily Wire items keep every control', () => {
    assert.ok(Object.values(sourceControls(dailyWireItem)).every(Boolean))
})

test('an item that is not saved yet keeps every control while it is added from The Daily Wire', () => {
    assert.ok(Object.values(sourceControls(undefined)).every(Boolean))
})

test('read schemas fill in the Source fields when an older backend leaves them out', () => {
    const parsed = sourceSchemas.ResolvedLinkReadSchema.parse({
        source: {id: 'stub', name: 'Stub', domains: ['stub.example'], features: []},
        kind: 'episode',
        slug: 'ep-1',
        url: 'https://stub.example/episode/ep-1',
        preview: {title: 'Episode 1'},
    })
    assert.equal(parsed.source.id, 'stub')
    assert.equal(sourceSchemas.hasSourceFeature(stubItem, sourceSchemas.SourceFeature.LIVE_EPISODES), false)
    assert.equal(sourceSchemas.sourceHas(parsed.source, sourceSchemas.SourceFeature.BROWSE), false)
})

test('links hand off to a show or a movie, and an episode opens its show', () => {
    const base = {source: {id: 'stub'}, preview: {title: 'Title'}}
    assert.deepEqual(
        plain(linkTarget({...base, kind: 'show', slug: 'a-show', url: 'https://stub.example/show/a-show'})),
        {sourceKey: 'stub', title: 'Title', kind: 'show', slug: 'a-show', url: 'https://stub.example/show/a-show'},
    )
    assert.equal(linkTarget({...base, kind: 'movie', slug: 'm', url: 'u'}).kind, 'movie')
    assert.deepEqual(
        plain(linkTarget({...base, kind: 'episode', slug: 'ep', url: 'e', showSlug: 'a-show', showUrl: 'https://stub.example/show/a-show'})),
        {sourceKey: 'stub', title: 'Title', kind: 'show', slug: 'a-show', url: 'https://stub.example/show/a-show'},
    )
    assert.equal(linkTarget({...base, kind: 'episode', slug: 'ep', url: 'e'}), null)
})

test('a video link hands off to the video itself', () => {
    const base = {source: {id: 'clips'}, preview: {title: 'A clip'}}
    assert.deepEqual(
        plain(linkTarget({...base, kind: 'video', slug: 'abc', url: 'https://clips.example/v/abc'})),
        {sourceKey: 'clips', title: 'A clip', kind: 'video', slug: 'abc', url: 'https://clips.example/v/abc'},
    )
    const parsed = sourceSchemas.ResolvedLinkReadSchema.parse({
        source: {id: 'clips', name: 'Clips', domains: ['clips.example'], features: ['videos']},
        kind: 'video', slug: 'abc', url: 'https://clips.example/v/abc', preview: {title: 'A clip'},
    })
    assert.equal(sourceSchemas.sourceHas(parsed.source, sourceSchemas.SourceFeature.VIDEOS), true)
})
