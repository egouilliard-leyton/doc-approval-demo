/// <reference types="vitest/config" />
import path from "path";
import { fileURLToPath } from "url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
  },
  // Vitest: pure-logic unit tests only, so the default node environment is used
  // (no jsdom). Tests live next to the code they cover as *.test.ts.
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
