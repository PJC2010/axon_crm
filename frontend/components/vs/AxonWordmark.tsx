/** The diamond mark + wordmark, server-renderable for the /vs pages. */
export function AxonWordmark() {
  return (
    <>
      <svg width={24} height={24} viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <mask id="axon-mark-vsnav">
          <rect width="32" height="32" fill="white" />
          <rect x="2" y="14.5" width="28" height="3" rx="1.5" fill="black" />
          <rect x="14.5" y="2" width="3" height="28" rx="1.5" fill="black" />
        </mask>
        <polygon points="16,5 27,16 16,27 5,16" fill="var(--color-accent)" mask="url(#axon-mark-vsnav)" />
        <circle cx="16" cy="16" r="1.5" fill="#f6f7f9" />
      </svg>
      <span className="lp-nav-wordmark">Axon</span>
    </>
  )
}
