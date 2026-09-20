import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 1_200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) {
            if (id.includes("maplibre-gl")) {
              return "vendor-maplibre";
            }
            if (id.includes("@deck.gl")) {
              return "vendor-deckgl";
            }
            if (id.includes("chart.js") || id.includes("react-chartjs-2")) {
              return "vendor-charts";
            }
            if (id.includes("@supabase")) {
              return "vendor-supabase";
            }
            if (id.includes("lucide-react")) {
              return "vendor-lucide";
            }
          }
        },
      },
    },
  },
});
