import './landing.css'
import LandingContent from '@/components/LandingContent'

export const metadata = {
  title: 'Axon — Know which homeowners in your ZIP need you',
  description:
    'Axon scores every property in your service area using county records, permits, equity, and storm data — and hands you an exclusive ranked call list. No shared leads. No contracts. Free 14-day trial.',
}

export default function LandingPage() {
  return (
    <div className="lp">
      <LandingContent />
    </div>
  )
}
