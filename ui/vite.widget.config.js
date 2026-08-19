import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Widget build config — produces a self-contained IIFE with React bundled in.
 * Output: dist-widget/chatbot-widget.iife.js
 *
 * Build:  npm run build:widget
 *
 * Embed on any host page (auto-injects FAB):
 *   <script src="chatbot-widget.iife.js" data-api-url="https://api.example.com"></script>
 *
 * Or declarative (no auto-inject):
 *   <faq-chat api-url="https://api.example.com" preaccepted></faq-chat>
 *   <script src="chatbot-widget.iife.js"></script>
 */
export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: 'src/widget/widget-embed.jsx',
      formats: ['iife'],
      name: 'FAQWidget',
      fileName: () => 'chatbot-widget',
    },
    outDir: 'dist-widget',
    emptyOutDir: true,
    rollupOptions: {
      // Bundle React and everything else inline — no external deps at runtime
      external: [],
    },
  },
})
