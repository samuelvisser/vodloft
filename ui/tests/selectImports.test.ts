import {strict as assert} from 'node:assert'
import {readFileSync, readdirSync, statSync} from 'node:fs'
import {join, relative} from 'node:path'
import {fileURLToPath} from 'node:url'
import {test} from 'node:test'

// The tests run from a bundle one folder below ui/.
const SOURCE = fileURLToPath(new URL('../src', import.meta.url))
const SHARED_SELECT = join('components', 'common', 'Select.tsx')

function sourceFiles(directory: string): string[] {
    return readdirSync(directory).flatMap((name) => {
        const path = join(directory, name)
        if (statSync(path).isDirectory()) return sourceFiles(path)
        return /\.tsx?$/.test(name) ? [path] : []
    })
}

test("dropdowns use the shared Select, so they all handle the keyboard the same way", () => {
    const offenders = sourceFiles(SOURCE)
        .filter((path) => relative(SOURCE, path) !== SHARED_SELECT)
        .filter((path) => /^import\s+(?!type\b)\w+[\s,][^;\n]*from\s+['"]react-select(\/[^'"]*)?['"]/m.test(readFileSync(path, 'utf8')))
        .map((path) => relative(SOURCE, path))
    assert.deepEqual(offenders, [])
})
