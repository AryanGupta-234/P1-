import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds into ../ui/next so the Python agent serves it as static files.
// No Node is needed on the target PC: the built output is committed.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "../ui/next",
    emptyOutDir: true,
    target: "es2020",
    cssCodeSplit: false,
    assetsInlineLimit: 0,
    sourcemap: false,
    chunkSizeWarningLimit: 400
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } }
});
