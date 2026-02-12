import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = (env.VITE_API_PROXY_TARGET || "http://localhost:8000").trim();

  return {
    base: mode === "production" ? "/admin/" : "/",
    plugins: [react()],
    server: {
      proxy: {
        "/admin/api": apiTarget,
        "/metrics": apiTarget,
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
    },
  };
});
