import './landing.css'
import LandingContent from '@/components/LandingContent'

export const metadata = {
  title: 'Axon — Built on data, focused on people',
  description: 'Axon turns public property data into ranked leads and runs your entire service-business back-office in one place.',
}

export default function LandingPage() {
  return (
    <div className="lp-root" data-theme="turquoise" data-bg="slate" data-texture="weave">
      <LandingContent />
    </div>
  )
}
