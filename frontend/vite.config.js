import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backendUrl = process.env.VITE_BACKEND_URL || "http://127.0.0.1:8010";
const modulePath = (relativePath) => fileURLToPath(new URL(relativePath, import.meta.url));

export default defineConfig({
  root: "react",
  plugins: [react()],
  optimizeDeps: {
    include: ["parse-diff"],
  },
  resolve: {
    alias: [
      { find: /^react\/jsx-runtime$/, replacement: modulePath("./react/src/vendor/reactJsxRuntimeGlobal.js") },
      { find: /^react\/jsx-dev-runtime$/, replacement: modulePath("./react/src/vendor/reactJsxRuntimeGlobal.js") },
      { find: /^react$/, replacement: modulePath("./react/src/vendor/reactGlobal.js") },
      { find: /^react-dom$/, replacement: modulePath("./react/src/vendor/reactDomGlobal.js") },
      { find: /^react-dom\/client$/, replacement: modulePath("./react/src/vendor/reactDomClientGlobal.js") },
    ],
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    minify: "esbuild",
    rollupOptions: {
      output: {
        manualChunks: {
          "markdown-vendor": ["markdown-it"],
          "virtuoso-vendor": ["react-virtuoso"],
          "interaction-vendor": ["@radix-ui/react-tooltip"],
          "icons-vendor": ["lucide-react"],
          "search-vendor": ["fuse.js"],
          "panel-vendor": ["react-resizable-panels"],
          "animation-vendor": ["@formkit/auto-animate", "thinking-orbs"],
          "diff-vendor": ["parse-diff"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": backendUrl,
      "/docs": backendUrl,
      "/redoc": backendUrl,
      "/openapi.json": backendUrl,
    },
  },
});
