/**
 * Bundle Analysis Configuration
 * Sprint 3 M-1: Performance Optimization
 * Vite configuration for bundle size analysis and optimization
 */

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { compression } from 'vite-plugin-compression2';
import { filesize } from 'rollup-plugin-filesize';

export default defineConfig({
  plugins: [
    react(),

    visualizer({
      filename: './dist/bundle-analysis.html',
      title: 'Ducta UI - Bundle Analysis',
      open: false,
      gzipSize: true,
      brotliSize: true,
    }),

    compression({
      algorithm: 'gzip',
      ext: '.gz',
    }),

    filesize({
      showBrotliSize: true,
      showGzippedSize: true,
      showMinifiedSize: true,
    }),
  ],

  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
        pure_funcs: ['console.log', 'console.info'],
      },
      output: {
        comments: false,
      },
    },
    target: 'esnext',
    sourcemap: false,
    reportCompressedSize: true,
    chunkSizeWarningLimit: 500,

    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-state': ['zustand', 'immer'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-utils': ['axios', 'js-yaml'],
          'feature-execution': [
            './src/components/Execution/ExecutionControls',
            './src/components/Execution/InlineLogs',
            './src/store/logsStore',
          ],
          'feature-editor': [
            './src/components/CodeEditor',
            './src/components/CodeEditorModal',
          ],
          'utils-all': [
            './src/utils/storage',
            './src/utils/logger',
            './src/utils/pipelineAdapter',
          ],
        },
        entryFileNames: 'js/[name]-[hash:8].js',
        chunkFileNames: 'js/[name]-[hash:8].chunk.js',
        assetFileNames: 'assets/[name]-[hash:8][extname]',
      },
    },
  },
});

// ── Bundle size targets (used by CI checks) ──────────────────────────────────

export const BUNDLE_TARGETS = {
  TOTAL_MAX: 500 * 1024,
  GZIP_MAX: 150 * 1024,
  VENDOR_MAX: 200 * 1024,
  FEATURE_MAX: 80 * 1024,
  UTILS_MAX: 50 * 1024,
  VENDOR_WARN: 150 * 1024,
  FEATURE_WARN: 60 * 1024,
};

export function checkBundleSizes(stats: Record<string, number>): {
  violations: Array<{ chunk: string; size: number; limit: number }>;
  warnings: Array<{ chunk: string; size: number; limit: number }>;
} {
  const violations: Array<{ chunk: string; size: number; limit: number }> = [];
  const warnings: Array<{ chunk: string; size: number; limit: number }> = [];

  for (const [chunk, size] of Object.entries(stats)) {
    if (chunk.includes('vendor-react')) {
      if (size > BUNDLE_TARGETS.VENDOR_MAX) {
        violations.push({ chunk, size, limit: BUNDLE_TARGETS.VENDOR_MAX });
      } else if (size > BUNDLE_TARGETS.VENDOR_WARN) {
        warnings.push({ chunk, size, limit: BUNDLE_TARGETS.VENDOR_WARN });
      }
    } else if (chunk.includes('feature-')) {
      if (size > BUNDLE_TARGETS.FEATURE_MAX) {
        violations.push({ chunk, size, limit: BUNDLE_TARGETS.FEATURE_MAX });
      } else if (size > BUNDLE_TARGETS.FEATURE_WARN) {
        warnings.push({ chunk, size, limit: BUNDLE_TARGETS.FEATURE_WARN });
      }
    }
  }

  return { violations, warnings };
}
