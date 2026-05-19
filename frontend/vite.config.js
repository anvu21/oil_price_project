import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    // Required for HMR inside Docker on Windows/Mac where inotify events
    // don't cross the container boundary — polling catches file changes instead.
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
})
