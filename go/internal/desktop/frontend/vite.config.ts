import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// base "./" because the window loads the files from its own embedded file system.
export default defineConfig({
  base: './',
  plugins: [svelte()],
  build: { outDir: 'dist', emptyOutDir: false, target: 'es2022', sourcemap: false },
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    // `npm run coverage` shows the figures; nothing fails on them (yet).
    coverage: { provider: 'v8', include: ['src/**/*.{ts,svelte}'], exclude: ['src/**/*.test.ts', 'src/**/*.d.ts'], reporter: ['text-summary', 'json-summary'] },
  },
});
