import './blueprint-scoped.css'
import './landing.css'
import ThemeSwitcher from '@/components/ThemeSwitcher'
import LandingContent from '@/components/LandingContent'

export const metadata = {
  title: 'Axon — Built on data, focused on people',
  description: 'Axon turns public property data into ranked leads and runs your entire service-business back-office in one place.',
}

export default function LandingPage() {
  return (
    <div className="lp-root" data-theme="cobalt" data-bg="dark-gray" data-texture="none">
      <ThemeSwitcher />
      {/* Blueprint dark theme scope — Blueprint's scoped CSS targets `.lp-root .bp6-dark` */}
      <div className="bp6-dark">
        <LandingContent />
      </div>
    </div>
  )
}
