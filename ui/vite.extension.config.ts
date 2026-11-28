import {resolve} from 'node:path'
import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react-swc'
import {fontAwesomeCompiler} from './scripts/font-awesome-compiler.mjs'
import {vodLoftVersionPlugin} from './vite.config'

// VODLoft's browser extension, built from the UI's own components, styles and API code into dist-extension: the
// folder a browser loads unpacked, and the one VODLoft offers as a zip.
export default defineConfig(({mode}) => ({
  root: resolve(__dirname, 'extension'),
  base: './',
  plugins: [
    vodLoftVersionPlugin(),
    fontAwesomeCompiler({proIcons: mode === 'pro-icons'}),
    react(),
  ],
  build: {
    outDir: resolve(__dirname, 'dist-extension'),
    emptyOutDir: true,
    // Extension pages may only run the extension's own scripts: no inline module preload helper.
    modulePreload: false,
    rollupOptions: {
      input: {
        popup: resolve(__dirname, 'extension/popup.html'),
        background: resolve(__dirname, 'src/extension/background.ts'),
      },
      output: {
        // The manifest names the background script.
        entryFileNames: (chunk) => chunk.name === 'background' ? 'background.js' : 'assets/[name]-[hash].js',
      },
    },
  },
}))
