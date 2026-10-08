import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { GoogleOAuthProvider } from '@react-oauth/google'
import './index.css'
import App from './App.jsx'

// ─── Replace this with your Google Client ID ──────────────────────────────────
// 1. Go to https://console.cloud.google.com/apis/credentials
// 2. Create a project → OAuth 2.0 Client ID → Web application
// 3. Add http://localhost:5173 to "Authorized JavaScript origins"
// 4. Paste the client ID below
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? ''

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <App />
    </GoogleOAuthProvider>
  </StrictMode>,
)
