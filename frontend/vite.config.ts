import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: forward /api to a locally-running mock (e.g., SAM local or the
// deployed API Gateway). In production the SPA reads apiEndpoint from config.json.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:3001", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  // First frontend test suite in the repo (What's New feed parser/filter/sanitizer).
  // A DOM environment is required because the RSS parser uses DOMParser and the
  // sanitizer uses DOMPurify — both browser APIs.
  //
  // jsdom, not happy-dom (DW-11 revised): happy-dom does not implement
  // DOMParser for "text/xml". It silently returns an HTML document whose
  // documentElement is <HTML>, never produces a <parsererror> node, and accepts
  // malformed XML — so RSS detection and malformed-feed handling could not be
  // tested at all, and the tests would have asserted behaviour that differs from
  // the browser. jsdom parses XML properly: documentElement is <rss>, malformed
  // input yields <parsererror>, and Atom/HTML documents are correctly rejected.
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
