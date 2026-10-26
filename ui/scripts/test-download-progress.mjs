import {build} from 'esbuild'
import {mkdtempSync, rmSync} from 'node:fs'
import {resolve, join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {execFileSync} from 'node:child_process'
const root = fileURLToPath(new URL('..', import.meta.url))
const directory = mkdtempSync(join(root, '.progress-tests-'))
try {
    const entryPoints = [
        resolve(root, 'tests/downloadProgress.test.tsx'),
        resolve(root, 'tests/safeDelayUi.test.tsx'),
    ]
    await build({
        entryPoints,
        outdir: directory,
        bundle: true,
        platform: 'node',
        format: 'esm',
        packages: 'external',
        jsx: 'automatic',
        loader: {'.css': 'empty'},
        plugins: [{
            name: 'vodloft-version-test',
            setup(build) {
                build.onResolve({filter: /^virtual:vodloft-version$/}, () => ({
                    path: 'vodloft-version',
                    namespace: 'vodloft-version-test',
                }))
                build.onLoad({filter: /.*/, namespace: 'vodloft-version-test'}, () => ({
                    contents: 'export const VODLOFT_VERSION = "test"',
                    loader: 'js',
                }))
            },
        }],
    })
    execFileSync(
        process.execPath,
        [
            '--test',
            join(directory, 'downloadProgress.test.js'),
            join(directory, 'safeDelayUi.test.js'),
        ],
        {stdio:'inherit'},
    )
} finally {
    rmSync(directory, {recursive:true,force:true})
}
