import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'

import type { components } from './api/types'
import { SyntheticDataBanner } from './components/SyntheticDataBanner'
import OrderDetailPage from './pages/OrderDetailPage'
import OverviewPage from './pages/OverviewPage'
import QueuePage from './pages/QueuePage'

type HealthResponse = components['schemas']['HealthResponse']

const NAV_LINK =
  'block rounded px-3 py-2 text-sm font-medium transition-colors duration-150'

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    fetch('/health')
      .then((res) => (res.ok ? res.json() : null))
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-300">
      <nav className="flex w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-900">
        <div className="border-b border-slate-800 p-4">
          <h1 className="text-lg font-bold tracking-tight text-slate-100">SENTINEL</h1>
          <p className="mt-0.5 text-xs text-slate-500">Return Abuse Detection</p>
        </div>
        <div className="flex-1 space-y-1 p-3">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `${NAV_LINK} ${isActive ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'}`
            }
          >
            Overview
          </NavLink>
          <NavLink
            to="/queue"
            className={({ isActive }) =>
              `${NAV_LINK} ${isActive ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'}`
            }
          >
            Review Queue
          </NavLink>
        </div>
        <div className="border-t border-slate-800 p-3">
          <p className="text-xs text-slate-600">
            {health ? `Policy ${health.policy_version} · ${health.policy_config_sha256}` : 'Policy —'}
          </p>
        </div>
      </nav>

      <main className="flex min-w-0 flex-1 flex-col">
        <SyntheticDataBanner />
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/orders/:orderId" element={<OrderDetailPage />} />
        </Routes>
      </main>
    </div>
  )
}
