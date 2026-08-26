import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      // The UI reuses the desktop app icon one directory above the Vite root.
      allow: [".."]
    }
  },
  build: {
    outDir: "../../reels_editor/desktop/ui",
    emptyOutDir: true
  }
});
