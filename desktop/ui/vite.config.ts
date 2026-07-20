import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../../reels_editor/desktop/ui",
    emptyOutDir: true
  }
});
