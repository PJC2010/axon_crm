import type { CSSProperties } from 'react'
import Image from 'next/image'
import { Camera } from 'lucide-react'

/**
 * Real-photography slots on the landing page.
 *
 * The page's whole argument is "local, verifiable, no hype" — a stock photo of
 * a smiling generic crew undercuts every honest claim above it. An unfilled
 * slot renders as an obvious, correctly-sized placeholder rather than pulling
 * in filler.
 *
 * The line is the claim, not the slot: an illustrative photo of the work may
 * fill a frame, but nothing here may imply a specific customer, job, or result
 * that does not exist — and a stand-in face attached to a real person's name is
 * a different kind of lie, so a portrait slot ships only with the real portrait.
 * Keep the `alt` describing what the photo actually shows, not what the slot
 * wishes for; each `brief` is the art direction still open for a real shoot.
 *
 * To fill one: drop the file in `frontend/public/photos/` and set `src` below.
 * Nothing else changes — each frame already reserves its aspect ratio, so the
 * layout does not shift when the image lands.
 */
export type PhotoKind = 'crew' | 'dialer'

/**
 * Photos default to `cover` — fill the frame, crop the overflow — which is
 * right for photography, where the frame is a window onto a larger scene.
 *
 * A device mockup is not photography: cropping it cuts through UI, which reads
 * as a rendering bug rather than a window. So the dialer uses `contain` and
 * shows the whole phone, and `.lp-feature-photo` gives its frame the height to
 * do that (see landing.css). The trade is legibility — a 1320x2868 phone shown
 * whole in a grid card renders its screen text at under 10px, so this is a
 * device shot and the card's caption carries the message in live text. Crop to
 * `cover` with a `position` anchored in the gaps between the mockup's own cards
 * if readable screen detail ever matters more than the whole device.
 */
export const PHOTOS: Record<
  PhotoKind,
  { src: string | null; ratio: string; brief: string; position?: string; fit?: 'cover' | 'contain' }
> = {
  crew: {
    src: '/photos/roof-inspection.jpg',
    ratio: '16 / 9',
    brief: 'A real Houston crew mid-job — truck, ladder, branded shirts. Shot on site, not staged.',
  },
  dialer: {
    src: '/photos/phone-dialer-3x.png',
    ratio: '3 / 2',
    brief: 'The dialer on a phone — the whole device, shown as a product shot.',
    fit: 'contain',
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
        <Image
          src={photo.src}
          alt={alt}
          fill
          sizes={sizes}
          style={{ objectFit: photo.fit ?? 'cover', objectPosition: photo.position ?? 'center' }}
        />
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
