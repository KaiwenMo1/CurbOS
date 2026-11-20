import assert from 'node:assert/strict'
import { execFile, execFileSync, spawn } from 'node:child_process'
import { on, once } from 'node:events'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createInterface } from 'node:readline'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { chromium } from 'playwright'
import { build, resolveConfig } from 'vite'

const {
  COMPOSE_PROJECT_NAME: project,
  CURBOS_TEST_DB_CONTAINER: container,
  CURBOS_TEST_DB_ENDPOINT: databaseEndpoint,
  POSTGRES_PASSWORD: password,
} = process.env

function docker(...args) {
  return execFileSync('docker', args, { encoding: 'utf8', timeout: 10_000 }).trim()
}

assert(
  /^curbos-db-test-[0-9a-f]{16}$/.test(project) && /^[0-9a-f]{64}$/.test(container) &&
    /^127\.0\.0\.1:[0-9]+$/.test(databaseEndpoint) && password,
  'Run make e2e-test to provision the isolated database',
)
const identity = docker('inspect', '--format',
  '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}} {{range index .NetworkSettings.Ports "5432/tcp"}}{{.HostIp}}:{{.HostPort}}{{end}}',
  container)
assert(identity === `${project}/db ${databaseEndpoint}`,
  'The endpoint must belong to the isolated Compose test database')

delete process.env.POSTGRES_PASSWORD
delete process.env.PGPASSWORD
delete process.env.CURBOS_DATABASE_URL

async function unusedLoopbackPort() {
  const probe = createServer()
  probe.listen(0, '127.0.0.1')
  await once(probe, 'listening')
  const { port } = probe.address()
  const closed = once(probe, 'close')
  probe.close()
  await closed
  return port
}

const webRoot = fileURLToPath(new URL('..', import.meta.url))
const backendRoot = fileURLToPath(new URL('../../../backend', import.meta.url))
const runFile = promisify(execFile)
const interruption = new AbortController()
const { signal } = interruption
let scratch
let api
let frontend
let browser
let browserClose
let paused = false

function closeBrowser() {
  if (browser) browserClose ??= browser.close()
  return browserClose
}

function interrupt(signalName) {
  interruption.abort(new Error(`E2E interrupted by ${signalName}`))
  void closeBrowser()?.catch(() => {}) // Report cleanup failures in finally.
}

process.on('SIGINT', interrupt)
process.on('SIGTERM', interrupt)

async function startApi(address) {
  const binary = join(scratch, 'curbos-api')
  await runFile('go', ['build', '-o', binary, './cmd/api'], {
    cwd: backendRoot,
    timeout: 120_000,
    signal,
  })
  signal.throwIfAborted()
  api = spawn(binary, [], {
    env: {
      ...process.env,
      CURBOS_HTTP_ADDR: address,
      CURBOS_DATABASE_URL: `postgres://curbos@${databaseEndpoint}/curbos?sslmode=disable`,
      CURBOS_READY_TIMEOUT: '1s',
      CURBOS_SHUTDOWN_TIMEOUT: '5s',
      PGPASSWORD: password,
    },
    stdio: ['ignore', 'ignore', 'pipe'],
  })
  await waitForOutput(api, api.stderr, (line) => {
    const event = JSON.parse(line)
    assert(event.msg === 'API started' && event.listen_addr === address,
      'The Go API did not start on the expected loopback listener')
    return address
  })
}

async function startPreview(outDir) {
  const vite = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
  // Vite preview handles SIGTERM by exiting its own process. Keep it outside this runner.
  frontend = spawn(process.execPath, [
    vite, 'preview', '--host', '127.0.0.1', '--port', '0', '--strictPort', '--outDir', outDir,
  ], {
    cwd: webRoot,
    env: { ...process.env, CI: 'true', NO_COLOR: '1' },
    stdio: ['ignore', 'pipe', 'inherit'],
  })
  return waitForOutput(frontend, frontend.stdout, (line) => line.match(/http:\/\/127\.0\.0\.1:[0-9]+/)?.[0])
}

async function waitForOutput(child, stream, pick) {
  await once(child, 'spawn')
  const lines = createInterface({ input: stream })
  try {
    for await (const [line] of on(lines, 'line', {
      close: ['close'],
      signal: AbortSignal.any([signal, AbortSignal.timeout(8_000)]),
    })) {
      const result = pick(line)
      if (result) return result
    }
    assert.fail('Test server exited without reporting its listener')
  } finally {
    lines.close()
    stream.resume()
  }
}

async function stopProcess(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return child?.exitCode
  const exited = once(child, 'exit', { signal: AbortSignal.timeout(8_000) })
  child.kill('SIGTERM')
  try {
    const [code] = await exited
    return code
  } catch (error) {
    if (child.kill('SIGKILL')) await once(child, 'exit', { signal: AbortSignal.timeout(2_000) })
    throw error
  }
}

async function waitForDatabase(apiOrigin) {
  const deadline = Date.now() + 10_000
  do {
    const response = await fetch(`${apiOrigin}/readyz`, {
      signal: AbortSignal.any([signal, AbortSignal.timeout(2_000)]),
    })
    const { status } = await response.json()
    if (response.status === 200 && status === 'ready') return
    await delay(100, undefined, { signal })
  } while (Date.now() < deadline)
  assert.fail('The same Go API did not recover PostgreSQL readiness')
}

try {
  scratch = await mkdtemp(join(tmpdir(), 'curbos-e2e-'))
  signal.throwIfAborted()
  const address = `127.0.0.1:${await unusedLoopbackPort()}`
  const apiOrigin = `http://${address}`
  await startApi(address)

  const publicDir = join(scratch, 'public')
  await mkdir(join(publicDir, 'basemap'), { recursive: true })
  // Synthetic, background-only basemap to exercise real MapLibre without a provider.
  await writeFile(join(publicDir, 'basemap/style.json'), JSON.stringify({
    version: 8,
    sources: {},
    layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e4e7db' } }],
  }))
  const config = {
    root: webRoot,
    envDir: false,
    publicDir,
    build: { outDir: join(scratch, 'dist'), emptyOutDir: false, reportCompressedSize: false },
    preview: { host: '127.0.0.1', port: 0, strictPort: true },
  }
  process.env.VITE_MAP_STYLE_URL = '/basemap/style.json'
  await build(config)
  signal.throwIfAborted()
  // Synthetic credentials must never escape the configuration diagnostic.
  const invalidOrigin = new URL(apiOrigin)
  invalidOrigin.username = 'synthetic'
  invalidOrigin.password = 'redaction-probe'
  for (const badOrigin of [invalidOrigin.href, 'http://192.0.2.1:8080', 'http://127.0.0.1:65536']) {
    process.env.CURBOS_DEV_API_ORIGIN = badOrigin
    await assert.rejects(() => resolveConfig({ ...config, logLevel: 'silent' }, 'serve', 'production', 'production', true), {
      message: 'CURBOS_DEV_API_ORIGIN must be http://127.0.0.1:<port> with a port from 1 to 65535.',
    })
  }
  process.env.CURBOS_DEV_API_ORIGIN = apiOrigin
  const origin = await startPreview(config.build.outDir)
  const foreignOriginProbe = await fetch(`${origin}/readyz`, {
    headers: { Origin: 'https://outside.example.test' },
    signal: AbortSignal.any([signal, AbortSignal.timeout(2_000)]),
  })
  assert.equal(foreignOriginProbe.status, 200)
  assert.equal(foreignOriginProbe.headers.get('access-control-allow-origin'), null)
  await foreignOriginProbe.body?.cancel()

  const browserEnv = Object.fromEntries(
    ['HOME', 'LANG', 'LD_LIBRARY_PATH', 'PATH', 'TMPDIR']
      .map((key) => [key, process.env[key]])
      .filter(([, value]) => value !== undefined),
  )
  browser = await chromium.launch({
    env: browserEnv,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    timeout: 15_000,
    handleSIGINT: false,
    handleSIGTERM: false,
  })
  signal.throwIfAborted()
  const context = await browser.newContext()
  const page = await context.newPage()
  page.setDefaultTimeout(10_000)
  const requestOrigins = new Set()
  page.on('request', (request) => requestOrigins.add(new URL(request.url()).origin))
  const notice = page.getByText('No verified parking data available.', { exact: true })
  const statusRegion = page.getByRole('region', { name: 'Backend status' })
  const retry = statusRegion.getByRole('button', { name: 'Check again' })

  async function checkReadiness(trigger, httpStatus, heading, readiness) {
    signal.throwIfAborted()
    const [response] = await Promise.all([
      page.waitForResponse((result) => result.url() === `${origin}/readyz`),
      trigger(),
    ])
    assert.equal(response.request().method(), 'GET')
    assert.equal(response.status(), httpStatus)
    if (readiness) {
      assert.equal(response.headers()['cache-control'], 'no-store')
      assert.match(response.headers()['content-type'], /^application\/json/)
      assert.deepEqual(await response.json(), { status: readiness })
    }
    await statusRegion.getByRole('heading', { name: heading }).waitFor()
    await notice.waitFor()
  }

  await checkReadiness(() => page.goto(origin), 200, 'Backend ready', 'ready')
  const canvas = page.locator('.map-canvas:not([inert]) canvas')
  const originalCanvas = await canvas.elementHandle()
  await page.getByRole('radio', { name: 'Going Out' }).check()
  await page.getByText('Metered street parking, cost, and walking distance.').waitFor()
  assert(await canvas.evaluate((current, original) => current === original, originalCanvas),
    'Changing trip mode recreated the MapLibre canvas')
  console.log('PASS browser readiness through Vite and Go, parking notice, and MapLibre mode switching')

  docker('pause', container)
  paused = true
  await checkReadiness(() => retry.click(), 503, 'Backend unavailable', 'not_ready')
  await statusRegion.getByText('The backend could not verify the database.').waitFor()
  const liveness = await fetch(`${apiOrigin}/healthz`, { signal: AbortSignal.timeout(2_000) })
  assert.equal(liveness.status, 200)
  assert.deepEqual(await liveness.json(), { status: 'ok' })
  docker('unpause', container)
  paused = false
  await waitForDatabase(apiOrigin)
  await checkReadiness(() => retry.click(), 200, 'Backend ready', 'ready')
  assert(await canvas.evaluate((current, original) => current === original, originalCanvas),
    'Changing readiness recreated the MapLibre canvas')
  console.log('PASS database outage and recovery with the same browser page, Go process, and map')

  assert.equal(await stopProcess(api), 0, 'Go API did not shut down cleanly')
  await checkReadiness(() => retry.click(), 502, 'Backend unavailable')
  await context.setOffline(true)
  await retry.click()
  await statusRegion.getByRole('heading', { name: 'Backend connection error' }).waitFor()
  await notice.waitFor()
  assert.deepEqual([...requestOrigins], [origin])
  console.log('PASS stopped API, offline browser, and redacted invalid proxy configuration')
} catch (error) {
  signal.throwIfAborted()
  throw error
} finally {
  // Attempt every cleanup even when an earlier cleanup fails.
  const cleanup = await Promise.allSettled([
    Promise.resolve().then(() => { if (paused) docker('unpause', container) }),
    Promise.resolve().then(closeBrowser),
    stopProcess(frontend),
    stopProcess(api),
  ])
  const failures = cleanup.flatMap((result) => result.status === 'rejected' ? [result.reason] : [])
  if (scratch) {
    await rm(scratch, { recursive: true, force: true }).catch((error) => { failures.push(error) })
  }
  if (failures.length) {
    console.error(new AggregateError(failures, 'E2E cleanup failed'))
    process.exitCode = 1
  }
  process.off('SIGINT', interrupt)
  process.off('SIGTERM', interrupt)
}
