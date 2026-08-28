import type { CSSProperties } from 'react'
import Image from 'next/image'
import { Camera } from 'lucide-react'

/**
 * Real-photography slots on the landing page.
 *
 * The page's whole argument is "local, verifiable, no hype" — a stock photo of
 * a smiling generic crew undercuts every honest claim above it. So these stay
 * empty until real Houston photography exists, and the frame renders as an
 * obvious, correctly-sized placeholder in the meantime.
 *
 * To fill one: drop the file in `frontend/public/photos/` and set `src` below.
 * Nothing else changes — each frame already reserves its aspect ratio, so the
 * layout does not shift when the image lands.
 */
export type PhotoKind = 'founder' | 'crew' | 'doorstep'

export const PHOTOS: Record<PhotoKind, { src: string | null; ratio: string; brief: string }> = {
  founder: {
    src: null,
    ratio: '1 / 1',
    brief: 'Pete — head and shoulders, natural light, Houston backdrop. Square crop.',
  },
  crew: {
    src: null,
    ratio: '4 / 3',
    brief: 'A real Houston crew mid-job — truck, ladder, branded shirts. Shot on site, not staged.',
  },
  doorstep: {
    src: null,
    ratio: '3 / 2',
    brief: 'One contractor at a front door, homeowner mid-conversation. Recognizably Harris County.',
  },
}

export function LandingPhoto({
  kind,
  alt,
  className,
  sizes = '(max-width: 860px) 100vw, 50vw',
}: {
  kind: PhotoKind
  alt: string
  className?: string
  sizes?: string
}) {
  const photo = PHOTOS[kind]
  const cls = className ? `lp-photo ${className}` : 'lp-photo'
  const style = { aspectRatio: photo.ratio } as CSSProperties

  if (photo.src) {
    return (
      <figure className={cls} style={style}>
        <Image src={photo.src} alt={alt} fill sizes={sizes} style={{ objectFit: 'cover' }} />
      </figure>
    )
  }

  return (
    <figure className={`${cls} is-empty`} style={style} role="img" aria-label={`Photo placeholder: ${alt}`}>
      <Camera size={20} aria-hidden="true" />
      <figcaption>
        <b>Photo to add</b>
        <span>{photo.brief}</span>
      </figcaption>
    </figure>
  )
}
