import { useCallback, useEffect, useRef, useState } from 'react'
import { getHazelReview } from '../services/portal/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'
const POLL_INTERVAL_MS = DEV_MODE ? 10000 : 30000
const POLLABLE_REVIEW_STATES = new Set(['under_review', 'action_required', 'response_submitted'])

export default function useCoverbaseReviewStatus(caseId, onSynced) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const onSyncedRef = useRef(onSynced)

  useEffect(() => { onSyncedRef.current = onSynced }, [onSynced])

  const refresh = useCallback(async () => {
    setIsRefreshing(true)
    setError('')
    try {
      const next = await getHazelReview(caseId)
      setData(next)
      await onSyncedRef.current?.(next)
      return next
    } catch (err) {
      setError(err.message)
      throw err
    } finally {
      setIsRefreshing(false)
    }
  }, [caseId])

  useEffect(() => {
    let cancelled = false
    let timer

    async function poll() {
      try {
        const next = await refresh()
        if (!cancelled && POLLABLE_REVIEW_STATES.has(next.review_state)) {
          timer = window.setTimeout(poll, POLL_INTERVAL_MS)
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, POLL_INTERVAL_MS)
      }
    }

    poll()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [refresh])

  useEffect(() => {
    const handleRefresh = () => { refresh().catch(() => {}) }
    window.addEventListener('hazel-review:refresh', handleRefresh)
    return () => window.removeEventListener('hazel-review:refresh', handleRefresh)
  }, [refresh])

  return { data, error, isRefreshing, refresh }
}
