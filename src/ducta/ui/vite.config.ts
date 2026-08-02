import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  plugins: [react()],

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
