import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import terser from '@rollup/plugin-terser';
import copy from 'rollup-plugin-copy';

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
    copy({
      targets: [
        {
          src: 'src/assets/images/*',
          dest: '../custom_components/exaviz/www/assets'
        }
      ],
      verbose: true,
      flatten: true
    }),
    production && terser(),
  ],
  external: [],
  watch: {
    clearScreen: false,
  },
}; 