import { useId, useRef, useState, type FormEvent } from 'react'

interface RouteUploadProps {
  isUploading: boolean
  isDirectAnalysis: boolean
  onUpload: (file: File) => Promise<void>
}

export function RouteUpload({ isUploading, isDirectAnalysis, onUpload }: RouteUploadProps) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || isUploading) return
    await onUpload(file)
    setFile(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <form className="upload-panel" onSubmit={handleSubmit}>
      <div className="panel-heading">
        <span className="eyebrow">New analysis</span>
        <span className="step-number">01</span>
      </div>
      <label className="file-picker" htmlFor={inputId}>
        <span className="file-picker-icon" aria-hidden="true">↗</span>
        <span>
          <strong>{file ? file.name : 'Choose a GPX track'}</strong>
          <small>{file ? `${(file.size / 1024).toFixed(1)} KB selected` : '.gpx files only'}</small>
        </span>
        <span className="browse-label">Browse</span>
      </label>
      <input
        ref={inputRef}
        id={inputId}
        className="visually-hidden"
        type="file"
        accept=".gpx,application/gpx+xml"
        disabled={isUploading}
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
      />
      <button className="primary-button" type="submit" disabled={!file || isUploading}>
        <span>{isUploading ? 'Analyzing route…' : isDirectAnalysis ? 'Analyze Route' : 'Upload & queue'}</span>
        <span aria-hidden="true">{isUploading ? '◌' : '→'}</span>
      </button>
    </form>
  )
}
