export const isVercelMode = import.meta.env.VITE_APP_MODE?.trim().toLowerCase() === 'vercel'

export const maxGpxUploadBytes = 4 * 1024 * 1024
export const maxGpxUploadMessage = 'GPX files must be 4 MB or smaller.'
