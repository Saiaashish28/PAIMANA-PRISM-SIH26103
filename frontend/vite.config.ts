import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.PRISM_API ?? "http://localhost:8000" },
  },
  build: { chunkSizeWarningLimit: 1600 },
});
