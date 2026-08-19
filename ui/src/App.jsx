import { Routes, Route, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import ChatPage    from './pages/ChatPage.jsx'
import AdminPage   from './pages/AdminPage.jsx'
import WidgetEmbedTestPage from './pages/WidgetEmbedTestPage.jsx'
import CookieBanner from './components/CookieBanner.jsx'
import { initGA, GA_ENABLED } from './analytics.js'
import './App.css'

export default function App() {
  const location = useLocation()
  const isWidgetTestPage = location.pathname === '/widget-embed'
  useEffect(() => {
    // Re-init GA on load if user already accepted cookies in a previous session
    if (GA_ENABLED && localStorage.getItem('faq_cookies') === 'accepted') {
      initGA()
    }
  }, [])

  return (
    <>
      <Routes>
        <Route path="/"             element={<ChatPage />} />
        <Route path="/admin/*"       element={<AdminPage />} />
        <Route path="/widget-embed"  element={<WidgetEmbedTestPage />} />
      </Routes>
      {!isWidgetTestPage && <CookieBanner />}
    </>
  )
}
