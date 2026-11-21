import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

function localApiProxy(mode: string) {
  const directory = fileURLToPath(new URL('.', import.meta.url))
  const { CURBOS_DEV_API_ORIGIN: origin = 'http://127.0.0.1:8080' } =
    loadEnv(mode, directory, 'CURBOS_DEV_API_ORIGIN')
  const port = /^http:\/\/127\.0\.0\.1:([0-9]{1,5})\/?$/.exec(origin)?.[1]
  if (!port || Number(port) < 1 || Number(port) > 65535) {
    throw new Error('CURBOS_DEV_API_ORIGIN must be http://127.0.0.1:<port> with a port from 1 to 65535.')
  }

  const target = `http://127.0.0.1:${Number(port)}`
  return { '^/readyz$': target, '^/v1/parking/': target }
}

export default defineConfig(({ command, mode }) => ({
  plugins: [react()],
  server: {
    cors: false,
    proxy: command === 'serve' && !process.env.VITEST ? localApiProxy(mode) : undefined,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
}))
