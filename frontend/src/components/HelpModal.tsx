import { useEffect, useId, useRef } from 'react'

interface HelpModalProps {
  isOpen: boolean
  showLocalStorageNote: boolean
  onClose: () => void
}

export function HelpModal({ isOpen, showLocalStorageNote, onClose }: HelpModalProps) {
  const titleId = useId()
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!isOpen) return

    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }

    document.addEventListener('keydown', handleKeyDown)
    closeButtonRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previouslyFocused?.focus()
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="help-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section
        className="help-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="help-modal-heading">
          <div>
            <span className="eyebrow">Route file guide</span>
            <h2 id={titleId}>How to get a GPX</h2>
          </div>
          <button
            ref={closeButtonRef}
            className="help-close"
            type="button"
            onClick={onClose}
            aria-label="Close GPX help"
          >
            ×
          </button>
        </div>

        <p>
          A GPX file contains GPS coordinates recorded during a walk, run, bike ride,
          hike, or other route.
        </p>

        <ul className="gpx-source-list">
          <li><strong>Strava</strong><span>Export a recorded activity as GPX</span></li>
          <li><strong>Garmin Connect</strong><span>Export an activity as GPX</span></li>
          <li><strong>Komoot</strong><span>Export or download a route</span></li>
          <li><strong>Ride with GPS</strong><span>Export a route as GPX</span></li>
          <li><strong>Other GPS apps</strong><span>Look for Export GPX or Download GPX</span></li>
        </ul>
        <p className="help-caveat">Export options vary by service, activity, and account.</p>

        <div className="help-steps">
          <span className="eyebrow">How it works</span>
          <ol>
            <li>Choose a GPX file or try the sample</li>
            <li>Analyze the route</li>
            <li>Explore the corrected distance and route statistics</li>
          </ol>
        </div>

        {showLocalStorageNote && (
          <p className="privacy-note">Saved Tracks are stored locally in your browser.</p>
        )}
      </section>
    </div>
  )
}
