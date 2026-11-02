import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端开发服务器：把 /api 代理到后端 127.0.0.1:18000，
// 这样浏览器里前端与后端同源，无需处理 CORS，SSE 也能正常流式返回。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:18000',
        changeOrigin: true,
      },
    },
  },
})
