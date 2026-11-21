import { useCallback, useEffect, useRef, useState } from 'react'
import {
  DiscoveryError, maxPages, requestTimeoutMs,
  type Coverage, type Detail, type DiscoveryClient, type VisibleRelease, type Zone,
} from './client'

const pollMs = 30_000
const viewportDebounceMs = 250
const maxViewportVertices = 100_000

type Failure = { kind: 'ERROR' | 'TIMEOUT' | 'WITHDRAWN'; code: string }
type Ready = {
  kind: VisibleRelease['kind']
  release: VisibleRelease
  features: Zone[]
  coverage: Coverage | 'NO_VIEWPORT' | 'ZOOM_IN'
  bounded: boolean
}
type View = Ready | Failure | { kind: 'NOT_CONFIGURED' | 'LOADING' | 'NO_PUBLIC_RELEASE' | 'WITHDRAWN' }

type Selection = { key: string; release: VisibleRelease; id: string }
type DetailResult = { selection: Selection; detail: Detail } | { selection: Selection; error: Failure }

function fromError(error: unknown): Failure {
  const code = error instanceof DiscoveryError ? error.code : 'API_UNAVAILABLE'
  return { kind: code === 'RELEASE_WITHDRAWN' ? 'WITHDRAWN' : code === 'TIMEOUT' ? 'TIMEOUT' : 'ERROR', code }
}

function invalidatesPin(error: Failure) {
  return ['RELEASE_WITHDRAWN', 'RELEASE_CONTEXT_MISMATCH', 'INVALID_CURSOR', 'RELEASE_NOT_FOUND', 'SCOPE_UNKNOWN'].includes(error.code)
}

function pinKey(r: VisibleRelease) {
  return `${r.scope}:${r.id}:${r.version}`
}

async function timed<T>(parent: AbortSignal, work: (signal: AbortSignal) => Promise<T>) {
  parent.throwIfAborted()
  const controller = new AbortController()
  let timer: number | undefined
  let abort = () => {}
  const interrupted = new Promise<never>((_, reject) => {
    abort = () => {
      controller.abort()
      reject(parent.reason)
    }
    parent.addEventListener('abort', abort, { once: true })
    timer = window.setTimeout(() => {
      reject(new DiscoveryError('TIMEOUT'))
      controller.abort()
    }, requestTimeoutMs)
  })
  try {
    return await Promise.race([interrupted, work(controller.signal)])
  } finally {
    window.clearTimeout(timer)
    parent.removeEventListener('abort', abort)
  }
}

async function readViewport(client: DiscoveryClient, r: VisibleRelease, bbox: string, signal: AbortSignal): Promise<Ready> {
  const base = { kind: r.kind, release: r, features: [], bounded: false }
  if (bbox === 'NO_VIEWPORT' || bbox === 'ZOOM_IN') return { ...base, coverage: bbox }

  const features: Zone[] = []
  const ids = new Set<string>()
  const cursors = new Set<string>()
  let cursor: string | null = null
  let coverage: Coverage | undefined
  let vertices = 0
  for (let i = 0; i < maxPages; i++) {
    signal.throwIfAborted()
    const page = await client.page(r, bbox, cursor, signal)
    if (coverage && page.coverage !== coverage) throw new DiscoveryError('RELEASE_CONTEXT_MISMATCH')
    coverage = page.coverage
    for (const zone of page.features) {
      if (ids.has(zone.id)) throw new DiscoveryError('INVALID_CURSOR')
      vertices += zone.geometry.coordinates.length
      if (vertices > maxViewportVertices) return { ...base, features, coverage, bounded: true }
      ids.add(zone.id)
      features.push(zone)
    }
    cursor = page.nextCursor
    if (!cursor) break
    if (cursors.has(cursor)) throw new DiscoveryError('INVALID_CURSOR')
    cursors.add(cursor)
  }
  return { ...base, features, coverage: coverage!, bounded: cursor !== null }
}

export function useDiscovery(client: DiscoveryClient, scope: string | null, viewport: { bbox: string; version: number }) {
  const { bbox, version } = viewport
  const [attempt, setAttempt] = useState(0)
  const [snapshot, setSnapshot] = useState<{ key: string; view: View }>()
  const [selection, setSelection] = useState<Selection>()
  const [detailResult, setDetailResult] = useState<DetailResult>()
  const rejected = useRef<{ key: string; error: Failure } | null>(null)
  const key = JSON.stringify([scope, version, attempt])
  const view: View = scope ? (snapshot?.key === key ? snapshot.view : { kind: 'LOADING' })
    : { kind: 'NOT_CONFIGURED' }
  const ready = 'release' in view ? view : undefined
  const selected = selection && ready && selection.key === key &&
    pinKey(selection.release) === pinKey(ready.release) &&
    ready.features.some((feature) => feature.id === selection.id) ? selection : undefined

  const retry = useCallback(() => {
    rejected.current = null
    setSelection(undefined)
    setAttempt((value) => value + 1)
  }, [])

  useEffect(() => {
    if (!scope) return
    const requestedScope = scope
    const controller = new AbortController()
    const { signal } = controller
    let timer: number
    let loadedPin: string | undefined
    let requested: VisibleRelease | undefined

    function show(view: View) {
      if (!signal.aborted) setSnapshot({ key, view })
    }

    async function load() {
      requested = undefined
      const release = await timed(signal, (querySignal) => client.current(requestedScope, querySignal))
      signal.throwIfAborted()
      if (!('id' in release)) {
        loadedPin = undefined
        show(release)
        return
      }
      const pin = pinKey(release)
      if (rejected.current?.key === pin) {
        show(rejected.current.error)
        return
      }
      if (loadedPin === pin) return
      requested = release
      show({ kind: 'LOADING' })
      const result = await timed(signal, (querySignal) => readViewport(client, release, bbox, querySignal))
      signal.throwIfAborted()
      loadedPin = pin
      show(result)
    }

    async function refresh() {
      try {
        await load()
      } catch (cause) {
        if (signal.aborted) return
        const error = fromError(cause)
        loadedPin = undefined
        show(error)
        setSelection(undefined)
        if (requested && invalidatesPin(error)) {
          rejected.current = { key: pinKey(requested), error }
          try {
            await load()
          } catch (recheckError) {
            if (signal.aborted) return
            const failure = fromError(recheckError)
            if (requested && invalidatesPin(failure)) rejected.current = { key: pinKey(requested), error: failure }
            show(failure)
          }
        }
      } finally {
        if (!signal.aborted) timer = window.setTimeout(refresh, pollMs)
      }
    }

    timer = window.setTimeout(refresh, bbox === 'NO_VIEWPORT' ? 0 : viewportDebounceMs)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [bbox, client, key, scope])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    async function inspect(current: Selection) {
      try {
        const detail = await timed(controller.signal, (signal) => client.detail(current.release, current.id, signal))
        if (!controller.signal.aborted) setDetailResult({ selection: current, detail })
      } catch (cause) {
        if (controller.signal.aborted) return
        const error = fromError(cause)
        if (invalidatesPin(error)) {
          rejected.current = { key: pinKey(current.release), error }
          setSelection(undefined)
          setAttempt((value) => value + 1)
        } else {
          setDetailResult({ selection: current, error })
        }
      }
    }
    void inspect(selected)
    return () => controller.abort()
  }, [client, selected])

  return {
    view, ready, retry,
    select(id: string) {
      if (ready?.features.some((feature) => feature.id === id)) setSelection({ key, release: ready.release, id })
    },
    dismiss() { setSelection(undefined) },
    selected,
    detail: selected && selected === detailResult?.selection ? detailResult : undefined,
  }
}
