import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El proxy evita problemas de CORS en desarrollo: /api -> FastAPI (puerto 8000)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { '/api': process.env.API_TARGET || 'http://127.0.0.1:8000' } },
})
