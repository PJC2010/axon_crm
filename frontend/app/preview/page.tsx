'use client'
import { useEffect, useState, useCallback } from 'react'
import {
  TrendingUp, Users, CheckSquare, DollarSign,
  Plus, FileText, Receipt, Kanban,
  AlertTriangle, Clock, AlertCircle,
  LogOut, Settings, BookOpen, ArrowRight,
  Percent, Sparkles, Activity,
  UserPlus, Target,
} from 'lucide-react'
import Link from 'next/link'
import { ScoreBadge } from '@/components/ScoreBadge'
import type { Lead, ForecastData } from '@/lib/types'

const MOCK_LEADS: Lead[] = [
  { id: 1, address: '1842 Westheimer Rd', city: 'Houston', state: 'TX', zip: '77006', latitude: null, longitude: null, year_built: 1987, square_footage: 3400, garage_spaces: 2, estimated_value: 425000, estimated_equity: 180000, last_sale_date: '2015-06-12', last_sale_price: 310000, owner_name: 'James Mitchell', owner_occupied: true, contact_phone: '(713) 555-0142', contact_email: 'jmitchell@example.com', contact_name: 'James Mitchell', contact_phone_alt: null, contact_email_alt: null, mailing_address: null, preferred_contact_method: null, best_time_to_call: null, zip_median_income: 78500, permit_count_24mo: 0, has_pool: true, has_cracked_slab: false, lead_score: 94, score_grade: 'A', vertical: 'hvac', neighborhood_value_ratio: 1.15, neighborhood_value_pctile: 0.82, neighborhood_value_basis: 'cell', hcad_neighborhood_code: '5412.02', hcad_neighborhood_name: 'WESTHEIMER OAKS', assigned_to: null, lead_source: 'hcad', status: 'qualified', estimated_job_value: 12500, stage_moved_at: '2026-06-05T10:00:00Z', score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-05-28T10:00:00Z', updated_at: '2026-06-05T10:00:00Z', archived_at: null },
  { id: 2, address: '504 River Oaks Blvd', city: 'Houston', state: 'TX', zip: '77019', latitude: null, longitude: null, year_built: 1992, square_footage: 4200, garage_spaces: 3, estimated_value: 680000, estimated_equity: 320000, last_sale_date: '2018-03-22', last_sale_price: 520000, owner_name: 'Patricia Nguyen', owner_occupied: true, contact_phone: '(713) 555-0287', contact_email: 'pnguyen@example.com', contact_name: 'Patricia Nguyen', contact_phone_alt: null, contact_email_alt: null, mailing_address: null, preferred_contact_method: null, best_time_to_call: null, zip_median_income: 125000, permit_count_24mo: 1, has_pool: false, has_cracked_slab: false, lead_score: 88, score_grade: 'A', vertical: 'epoxy', neighborhood_value_ratio: 1.40, neighborhood_value_pctile: 0.95, neighborhood_value_basis: 'cell', hcad_neighborhood_code: '4521.00', hcad_neighborhood_name: 'RIVER OAKS SEC 1-3', assigned_to: null, lead_source: 'rentcast', status: 'quote_sent', estimated_job_value: 6200, stage_moved_at: '2026-06-02T14:00:00Z', score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-05-20T10:00:00Z', updated_at: '2026-06-02T14:00:00Z', archived_at: null },
  { id: 3, address: '2901 Heights Blvd', city: 'Houston', state: 'TX', zip: '77008', latitude: null, longitude: null, year_built: 1975, square_footage: 2100, garage_spaces: 1, estimated_value: 340000, estimated_equity: 200000, last_sale_date: '2012-09-10', last_sale_price: 195000, owner_name: 'Robert Chen', owner_occupied: true, contact_phone: null, contact_email: null, contact_name: null, contact_phone_alt: null, contact_email_alt: null, mailing_address: null, preferred_contact_method: null, best_time_to_call: null, zip_median_income: 82000, permit_count_24mo: 0, has_pool: false, has_cracked_slab: false, lead_score: 82, score_grade: 'B', vertical: 'hvac', neighborhood_value_ratio: 0.95, neighborhood_value_pctile: 0.45, neighborhood_value_basis: 'cell', hcad_neighborhood_code: '6033.01', hcad_neighborhood_name: 'HOUSTON HEIGHTS', assigned_to: null, lead_source: 'hcad', status: 'contacted', estimated_job_value: 8500, stage_moved_at: '2026-05-18T10:00:00Z', score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-05-15T10:00:00Z', updated_at: '2026-05-18T10:00:00Z', archived_at: null },
  { id: 4, address: '7614 Bissonnet St', city: 'Houston', state: 'TX', zip: '77074', latitude: null, longitude: null, year_built: 1968, square_footage: 1850, garage_spaces: 1, estimated_value: 220000, estimated_equity: 140000, last_sale_date: '2008-11-04', last_sale_price: 145000, owner_name: 'Maria Lopez', owner_occupied: true, contact_phone: '(832) 555-0198', contact_email: null, contact_name: 'Maria Lopez', contact_phone_alt: null, contact_email_alt: null, mailing_address: null, preferred_contact_method: null, best_time_to_call: null, zip_median_income: 52000, permit_count_24mo: 2, has_pool: false, has_cracked_slab: true, lead_score: 76, score_grade: 'B', vertical: 'pool', neighborhood_value_ratio: 1.05, neighborhood_value_pctile: 0.60, neighborhood_value_basis: 'zip', hcad_neighborhood_code: null, hcad_neighborhood_name: null, assigned_to: null, lead_source: 'csv_import', status: 'new', estimated_job_value: 4800, stage_moved_at: null, score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-06-07T10:00:00Z', updated_at: '2026-06-07T10:00:00Z', archived_at: null },
  { id: 5, address: '3310 Montrose Blvd', city: 'Houston', state: 'TX', zip: '77006', latitude: null, longitude: null, year_built: 2001, square_footage: 2800, garage_spaces: 2, estimated_value: 510000, estimated_equity: 250000, last_sale_date: '2019-07-15', last_sale_price: 420000, owner_name: 'David Park', owner_occupied: true, contact_phone: '(713) 555-0331', contact_email: 'dpark@example.com', contact_name: 'David Park', contact_phone_alt: null, contact_email_alt: null, mailing_address: null, preferred_contact_method: null, best_time_to_call: null, zip_median_income: 78500, permit_count_24mo: 0, has_pool: true, has_cracked_slab: false, lead_score: 71, score_grade: 'C', vertical: 'solar', neighborhood_value_ratio: 1.25, neighborhood_value_pctile: 0.88, neighborhood_value_basis: 'cell', hcad_neighborhood_code: '5412.05', hcad_neighborhood_name: 'MONTROSE', assigned_to: null, lead_source: 'rentcast', status: 'new', estimated_job_value: 18000, stage_moved_at: null, score_updated_at: '2026-06-01T08:00:00Z', created_at: '2026-06-06T10:00:00Z', updated_at: '2026-06-06T10:00:00Z', archived_at: null },
]

const MOCK_FORECAST: ForecastData = {
  weighted_total: 28750,
  by_stage: [
    { stage: 'new', count: 2, raw_value: 22800, weight_pct: 10, weighted_value: 2280 },
    { stage: 'contacted', count: 1, raw_value: 8500, weight_pct: 25, weighted_value: 2125 },
    { stage: 'qualified', count: 1, raw_value: 12500, weight_pct: 50, weighted_value: 6250 },
    { stage: 'quote_sent', count: 1, raw_value: 6200, weight_pct: 75, weighted_value: 4650 },
  ],
}

const MOCK_PNL = [
  { month: 1, revenue: 18200, expenses: 6400, net: 11800 },
  { month: 2, revenue: 22100, expenses: 8900, net: 13200 },
  { month: 3, revenue: 19800, expenses: 7200, net: 12600 },
  { month: 4, revenue: 28400, expenses: 9100, net: 19300 },
  { month: 5, revenue: 34200, expenses: 11600, net: 22600 },
  { month: 6, revenue: 15400, expenses: 5800, net: 9600 },
]

const MOCK_PIPELINE = [
  { key: 'new', label: 'New', count: 47, color: 'var(--color-ink-300)' },
  { key: 'contacted', label: 'Contacted', count: 23, color: 'var(--color-info)' },
  { key: 'qualified', label: 'Qualified', count: 12, color: 'var(--color-accent)' },
  { key: 'quote_sent', label: 'Quote Sent', count: 8, color: 'var(--color-gold)' },
  { key: 'won', label: 'Won', count: 15, color: 'var(--color-moss)' },
]

const STATUS_LABELS: Record<string, string> = {
  new: 'New', contacted: 'Contacted', qualified: 'Qualified',
  quote_sent: 'Quote Sent', won: 'Won', lost: 'Lost',
}
const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  new:         { bg: 'var(--color-ink-50)', text: 'var(--color-ink-500)' },
  contacted:   { bg: 'var(--color-info-bg)', text: 'var(--color-info)' },
  qualified:   { bg: 'var(--color-accent-50)', text: 'var(--color-accent)' },
  quote_sent:  { bg: 'var(--color-gold-bg)', text: 'var(--color-gold)' },
  won:         { bg: 'var(--color-success-bg)', text: 'var(--color-success)' },
}

function fmtCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}k`
  return `$${n.toFixed(0)}`
}

function fmtCurrencyK(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

export default function PreviewPage() {
  const [wide, setWide] = useState(false)
  const [hoveredMonth, setHoveredMonth] = useState<number | null>(null)
  const [hoveredStage, setHoveredStage] = useState<string | null>(null)

  useEffect(() => {
    const check = () => setWide(window.innerWidth >= 640)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  const now      = new Date()
  const hour     = now.getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const dateStr  = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  const pipelineTotal = MOCK_PIPELINE.reduce((s, p) => s + p.count, 0)

  const totalRevenue = MOCK_PNL.reduce((s, m) => s + m.revenue, 0)
  const totalNet = MOCK_PNL.reduce((s, m) => s + m.net, 0)
  const maxBar = Math.max(...MOCK_PNL.flatMap(m => [m.revenue, m.expenses]))
  const MONTH_ABBR = ['J','F','M','A','M','J','J','A','S','O','N','D']

  const cx = 50, cy = 50, r = 36, strokeWidth = 10
  const circumference = 2 * Math.PI * r
  let offset = 0

  return (
    <div style={{ minHeight: '100vh', background: 'transparent', display: 'flex', flexDirection: 'column' }}>
      {/* ── Preview Banner ── */}
      <div style={{
        background: 'linear-gradient(90deg, var(--color-accent), var(--color-ocean-d))',
        color: 'white', textAlign: 'center', padding: '8px 16px', fontSize: 13, fontWeight: 500,
      }}>
        Preview Mode — Viewing dashboard with sample data
      </div>

      {/* ── Top Nav ── */}
      <header style={{
        height: 64, padding: wide ? '0 20px' : '0 10px', background: 'var(--color-paper)',
        borderBottom: '1px solid var(--color-ink-200)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'inherit' }}>
            <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <mask id="axon-mark-preview">
                <rect width="32" height="32" fill="white" />
                <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
                <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
              </mask>
              <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-preview)" />
              <circle cx="16" cy="16" r="1.5" fill="var(--color-ink-900)" />
            </svg>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--color-ink-900)' }}>
              Axon
            </span>
          </Link>
          {wide && <span style={{ color: 'var(--color-ink-300)', fontSize: 14 }}>·</span>}
          {wide && <span className="t-eyebrow">Preview</span>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
          {[
            { label: 'Leads', icon: <Users size={13} strokeWidth={1.5} /> },
            { label: 'Pipeline', icon: <Kanban size={13} strokeWidth={1.5} /> },
            { label: 'Tasks', icon: <CheckSquare size={13} strokeWidth={1.5} /> },
            { label: 'Expenses', icon: <Receipt size={13} strokeWidth={1.5} /> },
            { label: 'Books', icon: <BookOpen size={13} strokeWidth={1.5} /> },
          ].map(item => (
            <span key={item.label} className="dash-icon-btn" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '0 10px', fontSize: 13, cursor: 'default' }}>
              {item.icon}
              {wide && <span>{item.label}</span>}
            </span>
          ))}
        </div>
      </header>

      {/* ── Page Body ── */}
      <div style={{ flex: 1, maxWidth: 960, width: '100%', margin: '0 auto', padding: '24px 16px 40px' }}>

        {/* ── Hero Greeting ── */}
        <div style={{
          borderRadius: 'var(--radius-card)',
          background: 'linear-gradient(135deg, var(--color-accent) 0%, var(--color-ocean-d) 100%)',
          padding: '28px 24px', marginBottom: 20,
          position: 'relative', overflow: 'hidden',
        }}>
          <div style={{ position: 'absolute', top: -30, right: -20, width: 160, height: 160, borderRadius: '50%', background: 'rgba(255,255,255,0.06)' }} />
          <div style={{ position: 'absolute', bottom: -40, right: 60, width: 100, height: 100, borderRadius: '50%', background: 'rgba(255,255,255,0.04)' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, position: 'relative' }}>
            <div>
              <p style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 600, color: 'white', lineHeight: 1.2 }}>
                {greeting}, Pete
              </p>
              <p style={{ margin: '4px 0 0', fontSize: 13, color: 'rgba(255,255,255,0.65)' }}>{dateStr}</p>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p className="t-eyebrow" style={{ color: 'rgba(255,255,255,0.55)', margin: '0 0 4px' }}>Pipeline Value</p>
              <p className="tabular" style={{ margin: 0, fontSize: 30, fontWeight: 700, color: 'white', lineHeight: 1 }}>
                $142k
              </p>
            </div>
          </div>
        </div>

        {/* ── KPI Cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: wide ? 'repeat(5, 1fr)' : 'repeat(2, 1fr)', gap: 12, marginBottom: 20 }}>
          <KPICard icon={<TrendingUp size={16} strokeWidth={1.5} color="var(--color-accent)" />} label="Forecast" value="$29k" sub="weighted pipeline" />
          <KPICard icon={<Users size={16} strokeWidth={1.5} color="var(--color-accent)" />} label="Active Leads" value="90" sub="across all stages" />
          <KPICard icon={<CheckSquare size={16} strokeWidth={1.5} color="var(--color-accent)" />} label="Due Today" value="8" sub="on track" />
          <KPICard icon={<DollarSign size={16} strokeWidth={1.5} color="#4F7A4A" />} label="Collected YTD" value="$138k" sub="$9k outstanding" />
          <KPICard icon={<Percent size={16} strokeWidth={1.5} color="var(--color-moss)" />} label="Win Rate" value="38%" sub="12d avg cycle" />
        </div>

        {/* ── Quick Actions ── */}
        <div style={{ marginBottom: 24 }}>
          <p className="t-eyebrow" style={{ margin: '0 0 10px' }}>Quick Actions</p>
          <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '0 22px', minHeight: 44, borderRadius: 'var(--radius-pill)',
              background: 'var(--color-accent)', color: 'white',
              fontSize: 14, fontWeight: 600, whiteSpace: 'nowrap',
              boxShadow: '0 1px 4px rgba(26,90,117,0.25)', cursor: 'default',
            }}>
              <Plus size={15} strokeWidth={2} /> New Lead
            </span>
            {['View Pipeline', 'Create Invoice', 'Log Expense'].map(label => (
              <span key={label} style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '0 16px', minHeight: 44, borderRadius: 'var(--radius-pill)',
                background: 'var(--color-surface)', border: '1px solid var(--color-ink-300)',
                color: 'var(--color-ink-800)', fontSize: 13, fontWeight: 500,
                whiteSpace: 'nowrap', cursor: 'default',
              }}>
                {label}
              </span>
            ))}
          </div>
        </div>

        {/* ── AI Insights Panel ── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <div style={{
              width: 24, height: 24, borderRadius: 'var(--radius-button)',
              background: 'linear-gradient(135deg, var(--color-accent), var(--color-ocean-d))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Sparkles size={13} strokeWidth={1.8} color="white" />
            </div>
            <span className="t-eyebrow" style={{ letterSpacing: '0.1em' }}>AI Insights</span>
            <span style={{ fontSize: 10, color: 'var(--color-ink-400)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
              Based on your pipeline data
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { title: 'Win rate trending up', desc: 'Your 30-day win rate is 38% vs 32% over 90 days — your close process is improving.', type: 'positive' as const, icon: <TrendingUp size={15} strokeWidth={1.8} /> },
              { title: '3 leads going cold', desc: '3 contacted leads with no activity in 14+ days — worth $21k in potential revenue. Schedule follow-ups.', type: 'action' as const, icon: <Users size={15} strokeWidth={1.8} />, link: 'View leads' },
              { title: '5 hot leads ready to close', desc: 'You have 1 qualified and 1 quote-sent lead. Focus your energy here for fastest revenue.', type: 'positive' as const, icon: <Target size={15} strokeWidth={1.8} />, link: 'View pipeline' },
              { title: '$9,450 in overdue invoices', desc: '2 invoices past due. Send reminders to improve cash flow.', type: 'warning' as const, icon: <AlertTriangle size={15} strokeWidth={1.8} />, link: 'View invoices' },
            ].map(insight => {
              const styles = {
                action:   { bg: 'var(--color-accent-50)', border: 'var(--color-accent-300)', iconBg: 'var(--color-accent)' },
                positive: { bg: 'var(--color-success-bg)', border: 'var(--color-success)', iconBg: 'var(--color-moss)' },
                warning:  { bg: 'var(--color-warning-bg)', border: 'var(--color-warning)', iconBg: 'var(--color-gold)' },
              }[insight.type]
              return (
                <div key={insight.title} style={{
                  display: 'flex', alignItems: 'flex-start', gap: 12, padding: '14px 16px',
                  borderRadius: 'var(--radius-card)', background: styles.bg, border: `1px solid ${styles.border}`,
                }}>
                  <div style={{
                    width: 30, height: 30, borderRadius: 'var(--radius-button)', background: styles.iconBg,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1,
                  }}>
                    <span style={{ color: 'white', display: 'flex' }}>{insight.icon}</span>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ margin: '0 0 3px', fontSize: 14, fontWeight: 600, color: 'var(--color-ink-900)', lineHeight: 1.3 }}>{insight.title}</p>
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-ink-600)', lineHeight: 1.45 }}>{insight.desc}</p>
                  </div>
                  {insight.link && (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 500, color: styles.iconBg, whiteSpace: 'nowrap', flexShrink: 0, alignSelf: 'center' }}>
                      {insight.link} <ArrowRight size={12} strokeWidth={1.8} />
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Needs Attention ── */}
        <div style={{ marginBottom: 24 }}>
          <p className="t-eyebrow" style={{ margin: '0 0 10px' }}>Needs Attention</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderRadius: 'var(--radius-card)', background: 'var(--color-danger-bg)', borderLeft: '4px solid var(--color-danger)', minHeight: 44 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <AlertTriangle size={16} strokeWidth={1.5} color="var(--color-danger)" />
                <span style={{ fontSize: 14, color: 'var(--color-ink-900)', fontWeight: 500 }}>3 tasks overdue</span>
              </div>
              <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-danger)', fontWeight: 500 }}>
                Review <ArrowRight size={13} strokeWidth={1.5} />
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderRadius: 'var(--radius-card)', background: 'var(--color-warning-bg)', borderLeft: '4px solid var(--color-gold)', minHeight: 44 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Clock size={16} strokeWidth={1.5} color="var(--color-gold)" />
                <span style={{ fontSize: 14, color: 'var(--color-ink-900)', fontWeight: 500 }}>$9k in unpaid invoices</span>
              </div>
              <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-gold)', fontWeight: 500 }}>
                View <ArrowRight size={13} strokeWidth={1.5} />
              </span>
            </div>
          </div>
        </div>

        {/* ── Charts Row ── */}
        <div style={{ display: 'grid', gridTemplateColumns: wide ? '1.4fr 1fr' : '1fr', gap: 14, marginBottom: 24 }}>
          {/* Revenue Spark Chart */}
          <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '16px 18px', position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
              <div>
                <span className="t-eyebrow" style={{ marginBottom: 4, display: 'block' }}>Revenue Trend</span>
                <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)' }}>
                  {fmtCurrency(totalRevenue)}
                </span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 11, color: 'var(--color-ink-400)', marginBottom: 2 }}>Net Profit</div>
                <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--color-moss)' }}>
                  +{fmtCurrencyK(totalNet)}
                </div>
              </div>
            </div>
            <svg viewBox="0 0 100 100" style={{ width: '100%', height: 160, display: 'block' }} preserveAspectRatio="none"
              onMouseLeave={() => setHoveredMonth(null)}>
              <defs>
                <linearGradient id="prevRevGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-moss)" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="var(--color-moss)" stopOpacity="0.02" />
                </linearGradient>
              </defs>
              {[0.25, 0.5, 0.75].map(pct => (
                <line key={pct} x1="6" y1={12 + 70 * (1 - pct)} x2="94" y2={12 + 70 * (1 - pct)} stroke="var(--color-ink-100)" strokeWidth="0.3" />
              ))}
              {(() => {
                const points = MOCK_PNL.map((m, i) => ({
                  x: 6 + (i / (MOCK_PNL.length - 1)) * 88,
                  y: 12 + 70 - (m.revenue / maxBar) * 70,
                }))
                const expPts = MOCK_PNL.map((m, i) => ({
                  x: 6 + (i / (MOCK_PNL.length - 1)) * 88,
                  y: 12 + 70 - (m.expenses / maxBar) * 70,
                }))
                const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
                const area = `${line} L${points[points.length-1].x},82 L${points[0].x},82 Z`
                const expLine = expPts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
                return (
                  <>
                    <path d={area} fill="url(#prevRevGrad)" />
                    <path d={line} fill="none" stroke="var(--color-moss)" strokeWidth="1.5" strokeLinecap="round" />
                    <path d={expLine} fill="none" stroke="var(--color-rose)" strokeWidth="1" strokeDasharray="2,2" />
                    {MOCK_PNL.map((m, i) => (
                      <text key={i} x={points[i].x} y={96} textAnchor="middle" fill="var(--color-ink-400)" fontSize="3.5" fontFamily="var(--font-sans)">
                        {MONTH_ABBR[m.month - 1]}
                      </text>
                    ))}
                    {MOCK_PNL.map((_, i) => (
                      <rect key={`h-${i}`} x={points[i].x - 8} y={12} width={16} height={70} fill="transparent"
                        onMouseEnter={() => setHoveredMonth(i)} style={{ cursor: 'crosshair' }} />
                    ))}
                    {hoveredMonth !== null && (
                      <>
                        <line x1={points[hoveredMonth].x} y1={12} x2={points[hoveredMonth].x} y2={82} stroke="var(--color-ink-300)" strokeWidth="0.3" strokeDasharray="1,1" />
                        <circle cx={points[hoveredMonth].x} cy={points[hoveredMonth].y} r="2" fill="var(--color-moss)" stroke="white" strokeWidth="0.8" />
                        <circle cx={expPts[hoveredMonth].x} cy={expPts[hoveredMonth].y} r="1.5" fill="var(--color-rose)" stroke="white" strokeWidth="0.6" />
                      </>
                    )}
                  </>
                )
              })()}
            </svg>
            {hoveredMonth !== null && (
              <div style={{
                position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
                background: 'var(--color-ink-900)', color: 'white', borderRadius: 'var(--radius-button)',
                padding: '5px 10px', fontSize: 11, whiteSpace: 'nowrap', display: 'flex', gap: 12,
                boxShadow: 'var(--shadow-pop)',
              }}>
                <span style={{ color: 'var(--color-moss)' }}>Rev: {fmtCurrencyK(MOCK_PNL[hoveredMonth].revenue)}</span>
                <span style={{ color: 'var(--color-rose)' }}>Exp: {fmtCurrencyK(MOCK_PNL[hoveredMonth].expenses)}</span>
                <span style={{ fontWeight: 600 }}>Net: {fmtCurrencyK(MOCK_PNL[hoveredMonth].net)}</span>
              </div>
            )}
            <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
                <div style={{ width: 14, height: 2, background: 'var(--color-moss)', borderRadius: 1 }} /> Revenue
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-ink-500)' }}>
                <div style={{ width: 14, height: 2, background: 'var(--color-rose)', borderRadius: 1 }} /> Expenses
              </div>
            </div>
          </div>

          {/* Pipeline Ring Chart */}
          <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', padding: '16px 18px' }}>
            <span className="t-eyebrow" style={{ display: 'block', marginBottom: 12 }}>Pipeline Distribution</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
              <div style={{ position: 'relative', width: 120, height: 120, flexShrink: 0 }}>
                <svg viewBox="0 0 100 100" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
                  {MOCK_PIPELINE.map(seg => {
                    const pct = seg.count / pipelineTotal
                    const dashLen = pct * circumference
                    const gap = circumference - dashLen
                    const thisOffset = offset
                    offset += dashLen
                    const isHovered = hoveredStage === seg.key
                    return (
                      <circle key={seg.key} cx={cx} cy={cy} r={r} fill="none"
                        stroke={seg.color} strokeWidth={isHovered ? strokeWidth + 3 : strokeWidth}
                        strokeDasharray={`${dashLen} ${gap}`} strokeDashoffset={-thisOffset} strokeLinecap="butt"
                        onMouseEnter={() => setHoveredStage(seg.key)} onMouseLeave={() => setHoveredStage(null)}
                        style={{ cursor: 'pointer', transition: 'stroke-width 0.2s ease', opacity: hoveredStage && !isHovered ? 0.5 : 1 }}
                      />
                    )
                  })}
                </svg>
                <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
                  <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--color-ink-900)', lineHeight: 1 }}>{pipelineTotal}</span>
                  <span style={{ fontSize: 10, color: 'var(--color-ink-400)', marginTop: 2 }}>leads</span>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 0 }}>
                {MOCK_PIPELINE.map(seg => {
                  const pct = Math.round((seg.count / pipelineTotal) * 100)
                  const isHovered = hoveredStage === seg.key
                  return (
                    <div key={seg.key} style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '3px 6px',
                      borderRadius: 'var(--radius-button)',
                      background: isHovered ? 'var(--color-paper)' : 'transparent',
                      cursor: 'pointer',
                    }}
                      onMouseEnter={() => setHoveredStage(seg.key)} onMouseLeave={() => setHoveredStage(null)}>
                      <div style={{ width: 8, height: 8, borderRadius: '50%', background: seg.color, flexShrink: 0 }} />
                      <span style={{ fontSize: 12, color: 'var(--color-ink-700)', flex: 1 }}>{seg.label}</span>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-900)', fontFamily: 'var(--font-mono)' }}>{seg.count}</span>
                      <span style={{ fontSize: 10, color: 'var(--color-ink-400)', minWidth: 28, textAlign: 'right' }}>{pct}%</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>

        {/* ── Forecast Breakdown ── */}
        <div style={{ marginBottom: 24 }}>
          <p className="t-eyebrow" style={{ margin: '0 0 12px' }}>Weighted Forecast Breakdown</p>
          <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
            <div style={{ display: 'flex', padding: '10px 14px', borderBottom: '1px solid var(--color-ink-100)', gap: 8 }}>
              {['Stage', 'Leads', 'Raw', 'Wt%', 'Weighted'].map((h, i) => (
                <span key={h} style={{ flex: i === 0 ? 2 : 1, fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--color-ink-400)', textAlign: i === 0 ? 'left' : 'right' }}>{h}</span>
              ))}
            </div>
            {MOCK_FORECAST.by_stage.map(row => (
              <div key={row.stage} style={{ display: 'flex', padding: '8px 14px', borderBottom: '1px solid var(--color-ink-50)', alignItems: 'center', gap: 8 }}>
                <span style={{ flex: 2, fontSize: 13, fontWeight: 500, color: 'var(--color-ink-800)' }}>{STATUS_LABELS[row.stage] ?? row.stage}</span>
                <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)', textAlign: 'right' }}>{row.count}</span>
                <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-600)', textAlign: 'right' }}>{fmtCurrency(row.raw_value)}</span>
                <span className="tabular" style={{ flex: 1, fontSize: 13, color: 'var(--color-ink-400)', textAlign: 'right' }}>{row.weight_pct}%</span>
                <span className="tabular" style={{ flex: 1, fontSize: 13, fontWeight: 600, color: 'var(--color-accent)', textAlign: 'right' }}>{fmtCurrency(row.weighted_value)}</span>
              </div>
            ))}
            <div style={{ display: 'flex', padding: '10px 14px', background: 'var(--color-paper)', gap: 8 }}>
              <span style={{ flex: 2, fontSize: 13, fontWeight: 700, color: 'var(--color-ink-900)' }}>Total</span>
              <span style={{ flex: 1 }} /><span style={{ flex: 1 }} /><span style={{ flex: 1 }} />
              <span className="tabular" style={{ flex: 1, fontSize: 14, fontWeight: 700, color: 'var(--color-accent)', textAlign: 'right' }}>{fmtCurrency(MOCK_FORECAST.weighted_total)}</span>
            </div>
          </div>
        </div>

        {/* ── Activity Feed ── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Activity size={14} strokeWidth={1.8} color="var(--color-ink-400)" />
            <span className="t-eyebrow">Recent Activity</span>
          </div>
          <div style={{ background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
            {[
              { icon: <UserPlus size={13} strokeWidth={1.8} />, color: 'var(--color-accent)', title: 'James Mitchell', detail: 'Lead moved to qualified', time: '2h ago' },
              { icon: <FileText size={13} strokeWidth={1.8} />, color: 'var(--color-ink-500)', title: 'Invoice #INV-042', detail: 'Patricia Nguyen · $6,200 · sent', time: '5h ago' },
              { icon: <CheckSquare size={13} strokeWidth={1.8} />, color: 'var(--color-moss)', title: 'Follow up on quote', detail: 'Completed', time: '1d ago' },
              { icon: <DollarSign size={13} strokeWidth={1.8} />, color: 'var(--color-moss)', title: 'Invoice #INV-038', detail: 'Robert Chen · $8,500 · paid', time: '2d ago' },
              { icon: <UserPlus size={13} strokeWidth={1.8} />, color: 'var(--color-accent)', title: 'Maria Lopez', detail: 'Lead added', time: '3d ago' },
            ].map((item, idx) => (
              <div key={idx} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
                borderBottom: idx < 4 ? '1px solid var(--color-ink-100)' : 'none',
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: `color-mix(in srgb, ${item.color} 12%, transparent)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: item.color,
                }}>{item.icon}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title}</p>
                  <p style={{ margin: 0, fontSize: 11, color: 'var(--color-ink-400)' }}>{item.detail}</p>
                </div>
                <span style={{ fontSize: 10, color: 'var(--color-ink-400)', whiteSpace: 'nowrap', flexShrink: 0 }}>{item.time}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Top Scored Leads ── */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <p className="t-eyebrow" style={{ margin: 0 }}>Top Scored Leads</p>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-accent)', fontWeight: 500 }}>
              View all <ArrowRight size={13} strokeWidth={1.5} />
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {MOCK_LEADS.map(lead => {
              const sc = STATUS_COLORS[lead.status] ?? { bg: 'var(--color-ink-50)', text: 'var(--color-ink-500)' }
              return (
                <div key={lead.id} style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
                  borderRadius: 'var(--radius-card)', background: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', minHeight: 56,
                }}>
                  <ScoreBadge grade={lead.score_grade} score={lead.lead_score} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: 'var(--color-ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{lead.owner_name}</p>
                    <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--color-ink-400)' }}>{lead.city}, {lead.state}</p>
                  </div>
                  {lead.estimated_job_value != null && lead.estimated_job_value > 0 && (
                    <span className="tabular" style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-moss)', marginRight: 8 }}>
                      {fmtCurrency(lead.estimated_job_value)}
                    </span>
                  )}
                  <span style={{ padding: '3px 10px', borderRadius: 'var(--radius-pill)', background: sc.bg, color: sc.text, fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>
                    {STATUS_LABELS[lead.status] ?? lead.status}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

function KPICard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return (
    <div style={{
      background: 'var(--color-surface)', borderRadius: 'var(--radius-card)', boxShadow: 'var(--shadow-card)',
      padding: '16px', minHeight: 88, position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: 'linear-gradient(90deg, var(--color-accent) 0%, var(--color-accent-300) 100%)', opacity: 0.6 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {icon}
        <span className="t-eyebrow">{label}</span>
      </div>
      <p className="tabular" style={{ margin: '0 0 4px', fontSize: 26, fontWeight: 700, color: 'var(--color-ink-900)', lineHeight: 1 }}>{value}</p>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--color-ink-400)' }}>{sub}</p>
    </div>
  )
}
