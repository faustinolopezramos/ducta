import { defineConfig, mergeConfig } from "vite";
import app from "../vite.config";
export default mergeConfig(app, defineConfig({
  build: { outDir: "/private/tmp/claude-501/ducta-ux-check/dist", emptyOutDir: true, rollupOptions: { input: "/Users/faustinolopezramos/Desktop/ducta/src/ducta/ui/harness.html" } },
  preview: { port: 5199, strictPort: true, proxy: { "/api": { target: "http://127.0.0.1:8766", changeOrigin: true, ws: true } } },
}));
