import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import terser from '@rollup/plugin-terser';
import { cpSync } from 'node:fs';

const production = !process.env.ROLLUP_WATCH;

export default {
  input: 'src/index.ts',
  output: {
    file: '../custom_components/exaviz/www/exaviz-cards.js',
    format: 'es',
    sourcemap: !production,
  },
  plugins: [
    resolve({
      browser: true,
      preferBuiltins: false,
    }),
    typescript({
      declaration: false,
      outDir: null,
    }),
    {
      name: 'copy-assets',
      writeBundle() {
        cpSync('src/assets/images', '../custom_components/exaviz/www/assets', { recursive: true });
      },
    },
    production && terser(),
  ],
  external: [],
  watch: {
    clearScreen: false,
  },
}; 