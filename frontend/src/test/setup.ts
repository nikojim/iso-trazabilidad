import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { requests, server } from './server'

// Margen para máquinas cargadas (MUI en jsdom es lento en el primer render).
configure({ asyncUtilTimeout: 3000 })

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  requests.length = 0
})
afterAll(() => server.close())
