import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Where `npm run dev` forwards /api. Override with DUCTA_API_TARGET when the
// backend runs somewhere else.
const API_TARGET = process.env.DUCTA_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],

  // The README has always documented this ("Dev server (proxies /api to the
  // backend)") but the config did not do it, so `npm run dev` served /api from
  // Vite itself unless a developer set an absolute VITE_API_URL — which made
  // dev cross-origin, the one reason the session needed a client-held token.
  // Proxying makes dev same-origin, like the packaged UI that the API serves
  // from ui/dist in production.
  //
  // `ws: true` is not optional here: the log stream and the web terminal are
  // WebSockets, and without it they never reach the backend at all.
  server: {
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true, ws: true },
    },
  },

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@components": path.resolve(__dirname, "src/components"),
      "@hooks": path.resolve(__dirname, "src/hooks"),
      "@store": path.resolve(__dirname, "src/store"),
      "@api": path.resolve(__dirname, "src/api"),
      "@utils": path.resolve(__dirname, "src/utils"),
      "@types": path.resolve(__dirname, "src/types"),
      "@theme": path.resolve(__dirname, "src/theme"),
      "@pages": path.resolve(__dirname, "src/pages"),
    },
  },

  build: {
    outDir: "dist",
    assetsDir: "assets",
    minify: "esbuild",
    target: "esnext",
    sourcemap: false,
    chunkSizeWarningLimit: 500,

    rollupOptions: {
      onLog(level, log) {
        if (log.code === "MODULE_LEVEL_DIRECTIVE") return false;
      },
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/")) {
            // Before vendor-react, or the `/react/` test swallows @xyflow/react
            // and buries the canvas library in the chunk every page loads.
            // Isolated, it only costs the two routes that draw a DAG.
            if (id.includes("@xyflow")) return "vendor-flow";
            if (id.includes("/react-dom") || id.includes("/react/")) return "vendor-react";
            if (id.includes("react-router")) return "vendor-router";
            if (id.includes("@tanstack/react-query")) return "vendor-query";
            if (id.includes("zustand") || id.includes("immer")) return "vendor-state";
            if (id.includes("axios") || id.includes("js-yaml")) return "vendor-utils";
          }
        },
      },
    },
  },
});
