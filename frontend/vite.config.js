import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser only ever talks to :5173; /api is forwarded to Django on :8000,
// so session and CSRF cookies are same-origin and no CORS setup is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
