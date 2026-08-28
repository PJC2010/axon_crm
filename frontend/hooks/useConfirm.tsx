'use client'
import { useCallback, useRef, useState } from 'react'
import { ConfirmModal } from '@/components/ConfirmModal'

interface ConfirmOptions {
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
}

/**
 * Promise-based replacement for `window.confirm`.
 *
 * The native dialog is unstyled, blocks the whole tab, and on iOS names the
 * site in a way that reads as a browser warning rather than as the product
 * asking a question. This resolves to the same boolean, so the call sites keep
 * their shape:
 *
 *   const { confirm, confirmDialog } = useConfirm()
 *   if (!(await confirm({ title: 'Delete this task?', message: '…', danger: true }))) return
 *   …
 *   return <>{content}{confirmDialog}</>
 */
export function useConfirm() {
  const [pending, setPending] = useState<ConfirmOptions | null>(null)
  const resolveRef = useRef<((ok: boolean) => void) | null>(null)

  const confirm = useCallback((options: ConfirmOptions) => {
    setPending(options)
    return new Promise<boolean>(resolve => { resolveRef.current = resolve })
  }, [])

  const settle = useCallback((ok: boolean) => {
    setPending(null)
    resolveRef.current?.(ok)
    resolveRef.current = null
  }, [])

  const confirmDialog = pending ? (
    <ConfirmModal
      title={pending.title}
      message={pending.message}
      confirmLabel={pending.confirmLabel}
      danger={pending.danger}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null

  return { confirm, confirmDialog }
}
