import { useEffect, useState } from 'react'

const readinessTimeoutMs = 6_000

const messages = {
  loading: ['Checking backend…', ''],
  ready: ['Backend ready', 'The database passed the readiness check.'],
  'database-unavailable': ['Backend unavailable', 'The backend could not verify the database.'],
  unavailable: ['Backend unavailable', 'Check that the Go API is running, then try again.'],
  'network-error': ['Backend connection error', 'Check the API and frontend proxy, then try again.'],
  timeout: ['Backend connection error', 'The readiness check timed out.'],
} as const

type Readiness = keyof typeof messages

async function readBackendStatus(signal: AbortSignal): Promise<Readiness> {
  const response = await fetch('/readyz', {
    signal,
    cache: 'no-store',
    mode: 'same-origin',
    credentials: 'omit',
    redirect: 'error',
    headers: { Accept: 'application/json' },
  })
  const contentType = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()
  if ((response.status === 200 || response.status === 503) && contentType === 'application/json') {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'status' in body) {
      if (response.status === 200 && body.status === 'ready') return 'ready'
      if (response.status === 503 && body.status === 'not_ready') return 'database-unavailable'
    }
    return 'network-error'
  }
  return response.status >= 500 ? 'unavailable' : 'network-error'
}

export function BackendStatus() {
  const [status, setStatus] = useState<Readiness>('loading')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const deadline = window.setTimeout(() => {
      controller.abort()
      setStatus('timeout')
    }, readinessTimeoutMs)

    async function check() {
      try {
        const result = await readBackendStatus(controller.signal)
        if (!controller.signal.aborted) setStatus(result)
      } catch {
        if (!controller.signal.aborted) setStatus('network-error')
      } finally {
        window.clearTimeout(deadline)
      }
    }

    void check()
    return () => {
      window.clearTimeout(deadline)
      controller.abort()
    }
  }, [attempt])

  const [title, detail] = messages[status]

  return (
    <section className="backend-status" aria-label="Backend status">
      <div role="status">
        <h2>{title}</h2>
        {detail && <p>{detail}</p>}
      </div>
      <button
        type="button"
        aria-disabled={status === 'loading'}
        onClick={() => {
          if (status === 'loading') return
          setStatus('loading')
          setAttempt(attempt + 1)
        }}
      >
        Check again
      </button>
    </section>
  )
}
