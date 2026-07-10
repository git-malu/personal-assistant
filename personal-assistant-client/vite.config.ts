/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const serviceProxyTarget =
  process.env.PA_SERVICE_PROXY_TARGET ?? 'http://localhost:8080'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    proxy: {
      '/invocations/auth/oauth2/callback/m365-calendar': {
        target: serviceProxyTarget,
        changeOrigin: true,
        rewrite: (proxyPath) => proxyPath.replace(/^\/invocations/, ''),
      },
      '/invocations/playground': {
        target: serviceProxyTarget,
        changeOrigin: true,
        ws: true,
      },
      '/invocations': {
        target: serviceProxyTarget,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('X-HW-AgentGateway-User-Id', 'dev-user')
          })
        },
      },
    },
  },
})
