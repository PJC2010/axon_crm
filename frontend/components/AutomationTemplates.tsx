'use client'
import { useState } from 'react'
import { Zap, MessageSquare, FileText, ClipboardCheck, Trophy } from 'lucide-react'
import { createWorkflow, deleteWorkflow, updateWorkflow } from '@/lib/api'
import type { WorkflowRule } from '@/lib/types'

interface Template {
  key: string
  icon: React.ReactNode
  title: string
  description: string
  /** Editorial pick surfaced with a tag — a recommendation, not a usage stat. */
  recommended?: boolean
  trigger_config: { from_status?: string; to_status: string }
  action_config: { title: string; due_days_offset: number; priority: string }
}

const TEMPLATES: Template[] = [
  {
    key: 'tpl_contacted_quote',
    icon: <MessageSquare size={16} strokeWidth={1.8} />,
    title: 'First-contact quote reminder',
    description: 'When you mark a lead as Contacted → remind you to send a quote within 24 hours.',
    trigger_config: { to_status: 'contacted' },
    action_config: { title: 'Send quote to new contact', due_days_offset: 1, priority: 'high' },
  },
  {
    key: 'tpl_quote_followup',
    icon: <FileText size={16} strokeWidth={1.8} />,
    title: 'Quote follow-up nudge',
    description: 'When a quote is sent → follow up in 3 days if you haven\'t heard back.',
    recommended: true,
    trigger_config: { to_status: 'quote_sent' },
    action_config: { title: 'Follow up on pending quote', due_days_offset: 3, priority: 'normal' },
  },
  {
    key: 'tpl_qualified_visit',
    icon: <ClipboardCheck size={16} strokeWidth={1.8} />,
    title: 'Site visit scheduler',
    description: 'When a lead is Qualified → create a task to schedule the job site visit.',
    trigger_config: { to_status: 'qualified' },
    action_config: { title: 'Schedule site visit', due_days_offset: 2, priority: 'high' },
  },
  {
    key: 'tpl_won_invoice',
    icon: <Trophy size={16} strokeWidth={1.8} />,
    title: 'Win → invoice today',
    description: 'When you mark a deal as Won → remind yourself to create the invoice right away.',
    trigger_config: { to_status: 'won' },
    action_config: { title: 'Create invoice for won job', due_days_offset: 0, priority: 'urgent' },
  },
]

interface Props {
  workflows: WorkflowRule[]
  onWorkflowsChange: (w: WorkflowRule[]) => void
  onToast?: (msg: string, v?: 'success' | 'error') => void
}

function isTemplateActive(key: string, workflows: WorkflowRule[]): WorkflowRule | undefined {
  return workflows.find(w => w.name.startsWith(key))
}

export function AutomationTemplates({ workflows, onWorkflowsChange, onToast }: Props) {
  const [toggling, setToggling] = useState<string | null>(null)

  async function handleToggle(tpl: Template) {
    if (toggling) return
    setToggling(tpl.key)
    const existing = isTemplateActive(tpl.key, workflows)
    try {
      if (existing) {
        if (existing.is_active) {
          await updateWorkflow(existing.id, { is_active: false })
          onWorkflowsChange(workflows.map(w => w.id === existing.id ? { ...w, is_active: false } : w))
          onToast?.('Automation paused', 'success')
        } else {
          await updateWorkflow(existing.id, { is_active: true })
          onWorkflowsChange(workflows.map(w => w.id === existing.id ? { ...w, is_active: true } : w))
          onToast?.('Automation activated', 'success')
        }
      } else {
        const created = await createWorkflow({
          name: `${tpl.key} — ${tpl.title}`,
          trigger_config: tpl.trigger_config,
          action_config: tpl.action_config,
        })
        onWorkflowsChange([...workflows, created])
        onToast?.('Automation enabled', 'success')
      }
    } catch {
      onToast?.('Failed to update automation', 'error')
    } finally {
      setToggling(null)
    }
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 12 }}>
        <Zap size={13} strokeWidth={2} color="var(--color-accent)" />
        <span className="t-eyebrow">Smart Automations</span>
        <span style={{ fontSize: 11, color: 'var(--color-ink-400)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
          One-click setup
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
        {TEMPLATES.map(tpl => {
          const existing = isTemplateActive(tpl.key, workflows)
          const isOn = existing?.is_active === true
          const isPending = toggling === tpl.key

          return (
            <div
              key={tpl.key}
              style={{
                padding: '14px 16px',
                borderRadius: 'var(--radius-card)',
                background: isOn ? 'var(--color-accent-50)' : 'var(--color-surface)',
                border: isOn
                  ? '1.5px solid var(--color-accent-200)'
                  : '1.5px solid var(--color-ink-200)',
                display: 'flex', alignItems: 'flex-start', gap: 12,
                transition: 'border-color 0.2s, background 0.2s',
              }}
            >
              <div style={{
                width: 32, height: 32, borderRadius: 'var(--radius-button)',
                background: isOn ? 'var(--color-accent)' : 'var(--color-ink-100)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0,
                color: isOn ? 'white' : 'var(--color-ink-500)',
              }}>
                {tpl.icon}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ margin: '0 0 3px', fontSize: 13, fontWeight: 600, color: 'var(--color-ink-900)' }}>
                  {tpl.title}
                  {tpl.recommended && (
                    <span style={{
                      marginLeft: 8, padding: '1px 8px', borderRadius: 'var(--radius-pill)',
                      background: 'var(--color-gold-soft)', color: 'var(--color-gold)',
                      fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em',
                      verticalAlign: 'middle',
                    }}>
                      Recommended
                    </span>
                  )}
                </p>
                <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-500)', lineHeight: 1.45 }}>
                  {tpl.description}
                </p>
              </div>
              <button
                type="button"
                onClick={() => handleToggle(tpl)}
                disabled={isPending}
                title={isOn ? 'Pause this automation' : 'Activate this automation'}
                style={{
                  width: 40, height: 22, borderRadius: 11, border: 'none',
                  background: isOn ? 'var(--color-accent)' : 'var(--color-ink-300)',
                  position: 'relative', cursor: isPending ? 'not-allowed' : 'pointer',
                  transition: 'background 0.2s', flexShrink: 0,
                  opacity: isPending ? 0.6 : 1,
                }}
              >
                <div style={{
                  width: 16, height: 16, borderRadius: '50%',
                  background: 'white',
                  position: 'absolute', top: 3,
                  left: isOn ? 21 : 3,
                  transition: 'left 0.2s',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                }} />
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
