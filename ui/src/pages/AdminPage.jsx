import { useState } from 'react'
import { Link } from 'react-router-dom'
import DocumentsTab  from '../components/admin/DocumentsTab.jsx'
import SettingsTab   from '../components/admin/SettingsTab.jsx'
import AnalyticsTab  from '../components/admin/AnalyticsTab.jsx'
import './AdminPage.css'

const TABS = [
  { id: 'documents',  label: 'Documents'  },
  { id: 'settings',   label: 'Settings'   },
  { id: 'analytics',  label: 'Analytics'  },
]

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('documents')

  return (
    <div className="admin-page">
      <header className="admin-header">
        <div className="admin-header__brand">
          <span className="admin-header__logo">K</span>
          <span className="admin-header__title">
            FAQs <span className="admin-header__badge">Admin</span>
          </span>
        </div>
        <Link to="/" className="admin-header__back">← Back to Chat</Link>
      </header>

      <nav className="admin-nav" role="tablist" aria-label="Admin sections">
        {TABS.map(tab => (
          <button
            key={tab.id}
            id={`tab-${tab.id}`}
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`panel-${tab.id}`}
            className={`admin-tab ${activeTab === tab.id ? 'admin-tab--active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main
        id={`panel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`tab-${activeTab}`}
        tabIndex={0}
        className="admin-content"
      >
        {activeTab === 'documents'  && <DocumentsTab />}
        {activeTab === 'settings'   && <SettingsTab />}
        {activeTab === 'analytics'  && <AnalyticsTab />}
      </main>
    </div>
  )
}
