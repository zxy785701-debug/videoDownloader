import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'
import { fileURLToPath } from 'node:url'
import { optionsFromEnv, seoPlugin } from './seo/build.ts'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [vue(), tailwindcss(), seoPlugin(optionsFromEnv(loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), 'SEO_')))],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
