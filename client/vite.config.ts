import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": process.env.LZ_API_PROXY || "http://127.0.0.1:8001" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
