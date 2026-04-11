import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;
const appRoot = realpathSync(fileURLToPath(new URL(".", import.meta.url)));

// https://vite.dev/config/
export default defineConfig(async () => ({
  root: appRoot,
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("react-syntax-highlighter") || id.includes("refractor") || id.includes("prism")) {
            return "markdown-code";
          }
          if (id.includes("react-markdown") || id.includes("remark-gfm") || id.includes("micromark") || id.includes("mdast-util") || id.includes("unist-util")) {
            return "markdown-render";
          }
          return undefined;
        },
      },
    },
  },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
