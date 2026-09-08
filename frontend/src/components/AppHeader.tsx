interface AppHeaderProps {
  status: string
  hasError: boolean
}

export function AppHeader({ status, hasError }: AppHeaderProps) {
  return (
    <header className="app-header">
      <a className="brand" href="#app" aria-label="Fractal Route home">
        <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
        <span className="brand-copy">
          <strong>Fractal Route</strong>
        </span>
      </a>
      <span className={`app-state${hasError ? ' app-state-error' : ''}`}>
        <i aria-hidden="true" />
        {status}
      </span>
    </header>
  )
}
