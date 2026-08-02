'use client'

// Meta (Facebook) pixel base tag. The GA equivalent comes ready-made from
// @next/third-parties; Meta ships no such wrapper, so the snippet lives here.
//
// Gated on NEXT_PUBLIC_META_PIXEL_ID — unset means the pixel never loads,
// matching the GA tag in app/layout.tsx and the repo-wide "missing key =
// feature skipped" convention. Conversion events go through lib/analytics.ts.
import Script from 'next/script'
import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { trackMetaPageView } from '@/lib/analytics'

const PIXEL_ID = process.env.NEXT_PUBLIC_META_PIXEL_ID

export default function MetaPixel() {
  // usePathname (not useSearchParams) on purpose: useSearchParams needs a
  // Suspense boundary and would opt every page under the root layout out of
  // static rendering. Query-only navigations aren't worth that trade.
  const pathname = usePathname()
  const mounted = useRef(false)

  // Unlike gtag, fbq does not observe history changes — the base snippet fires
  // PageView exactly once, so client-side route changes need a manual send.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true // first render: the snippet below already sent it
      return
    }
    trackMetaPageView()
  }, [pathname])

  if (!PIXEL_ID) return null

  return (
    <Script id="meta-pixel" strategy="afterInteractive">
      {`!function(f,b,e,v,n,t,s)
      {if(f.fbq)return;n=f.fbq=function(){n.callMethod?
      n.callMethod.apply(n,arguments):n.queue.push(arguments)};
      if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
      n.queue=[];t=b.createElement(e);t.async=!0;
      t.src=v;s=b.getElementsByTagName(e)[0];
      s.parentNode.insertBefore(t,s)}(window,document,'script',
      'https://connect.facebook.net/en_US/fbevents.js');
      fbq('init', '${PIXEL_ID}');
      fbq('track', 'PageView');`}
    </Script>
  )
}
