import './landing.css'
import LandingContent from '@/components/LandingContent'

export const metadata = {
  title: 'Axon — Built on data, focused on people',
  description: 'Axon turns public property data into ranked leads and runs your entire local service business back office in one place.',
}

export default function LandingPage() {
  return (
    <div className="lp">
      <LandingContent />
    </div>
  )
}
