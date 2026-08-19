import { Link } from 'react-router-dom'
import './Header.css'

// FAQ demo brand colours: #003087 (navy) / #E31837 (red)
export default function Header() {
  return (
    <header className="header">
      <div className="header-brand">
        <span className="header-logo">F</span>
        <span className="header-name">FAQs</span>
      </div>
      <div className="header-right">
        <span className="header-title">Help Centre</span>
        <Link to="/widget-embed" className="header-widget-link">Widget demo</Link>
      </div>
    </header>
  )
}
