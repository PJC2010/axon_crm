'use client'
import { useRef } from 'react'
import type { Lead, LeadStatus, PipelineCardLead } from '@/lib/types'
import { KanbanCard } from '@/components/KanbanCard'
import { useKanbanDnd } from '@/hooks/useKanbanDnd'
import { DEMO_STAGES, groupByStage, stageStats } from '@/lib/demoData'

interface Props {
  leads: Lead[]
  /** Fired when a card is dropped on a different column. */
  onMove: (id: number, toStage: LeadStatus) => void
  /** Tap/click on a card (not a drag). */
  onOpen: (id: number) => void
  /** The card's quick-task "+" button. */
  onQuickTask: (card: PipelineCardLead) => void
}

/**
 * The real Kanban board, demo-fed: same card component, same pointer-events
 * drag hook (mouse + touch), same column layout as app/pipeline/page.tsx —
 * but state lives in the demo page instead of the API.
 */
export function DemoPipeline({ leads, onMove, onOpen, onQuickTask }: Props) {
  const boardRef = useRef<HTMLDivElement | null>(null)
  const groups = groupByStage(leads)
  const stats = stageStats(leads)

  const { dragItem, draggingId, overStage, onPointerDown, setGhostNode } = useKanbanDnd<PipelineCardLead>({
    getId: card => card.id,
    getStage: card => card.status,
    onDrop: (card, toStage) => onMove(card.id, toStage as LeadStatus),
    onSelect: card => onOpen(card.id),
    scrollRef: boardRef,
  })

  const fmtValue = (v: number) => (v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`)

  return (
    <div>
      <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-ink-500)' }}>
        Drag a card between stages — the forecast on the dashboard moves with it.
        On a phone, press and hold to pick a card up.
      </p>
      <div ref={boardRef} style={{ overflowX: 'auto', paddingBottom: 8 }}>
        <div style={{ display: 'flex', gap: 12, minWidth: 'max-content' }}>
          {DEMO_STAGES.map(stage => {
            const cards = groups[stage.key] ?? []
            const stat = stats[stage.key]
            const isOver = overStage === stage.key && dragItem != null && dragItem.status !== stage.key
            return (
              <div
                key={stage.key}
                data-stage-key={stage.key}
                style={{
                  width: 240,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  background: isOver ? 'var(--color-surface)' : 'transparent',
                  outline: isOver ? '2px dashed var(--color-accent)' : '2px dashed transparent',
                  outlineOffset: -2,
                  borderRadius: 'var(--radius-card)',
                  transition: 'background 0.15s, outline-color 0.15s',
                  padding: 8,
                  minHeight: 360,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: stage.color, flexShrink: 0 }} />
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-700)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      {stage.label}
                    </span>
                  </div>
                  <span style={{ fontSize: 11, color: 'var(--color-ink-400)' }}>
                    {stat.count}
                    {stat.total_value ? ` · ${fmtValue(stat.total_value)}` : ''}
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                  {cards.map(card => (
                    <div
                      key={card.id}
                      onPointerDown={e => onPointerDown(e, card)}
                      style={{
                        opacity: draggingId === card.id ? 0.4 : 1,
                        touchAction: 'pan-x pan-y',
                        WebkitUserSelect: 'none',
                        userSelect: 'none',
                        WebkitTouchCallout: 'none',
                      }}
                    >
                      <KanbanCard lead={card} onQuickTask={onQuickTask} />
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {dragItem && (
        <div
          ref={setGhostNode}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: 224,
            margin: '-20px 0 0 -16px',
            pointerEvents: 'none',
            zIndex: 1000,
            opacity: 0.95,
            willChange: 'transform',
          }}
        >
          <KanbanCard lead={dragItem} ghost />
        </div>
      )}
    </div>
  )
}
