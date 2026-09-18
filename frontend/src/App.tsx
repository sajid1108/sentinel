import { useEffect, useState } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import type { components } from './api/types'

type HealthResponse = components['schemas']['HealthResponse']

function SyntheticDataBanner() {
  return (
    <div className="bg-amber-900/30 border border-amber-500/30 text-amber-200 text-sm px-4 py-2 text-center">
      Synthetic data is used to validate the architecture, policy behaviour, auditability, and coordinated-pattern detection. Real deployment would require merchant-specific historical data and prospective validation.
    </div>
  )
}

function OverviewPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100 mb-4">Overview</h1>
      <p className="text-slate-400">Activity and backtest metrics will appear here.</p>
    </div>
  )
}

function QueuePage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100 mb-4">Review Queue</h1>
      <p className="text-slate-400">Order queue with filters will appear here.</p>
    </div>
  )
}

function OrderDetailPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-slate-100 mb-4">Order Detail</h1>
      <p className="text-slate-400">Order detail view will appear here.</p>
    </div>
  )
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    fetch('/health')
      .then((res) => (res.ok ? res.json() : null))
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-300 flex">
      {/* Sidebar */}
      <nav className="w-56 bg-slate-900 border-r border-slate-800 flex flex-col">
        <div className="p-4 border-b border-slate-800">
          <h1 className="text-lg font-bold text-slate-100 tracking-tight">SENTINEL</h1>
          <p className="text-xs text-slate-500 mt-0.5">Return Abuse Detection</p>
        </div>
        <div className="flex-1 p-3 space-y-1">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `block px-3 py-2 rounded text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-slate-800 text-slate-100'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`
            }
          >
            Overview
          </NavLink>
          <NavLink
            to="/queue"
            className={({ isActive }) =>
              `block px-3 py-2 rounded text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-slate-800 text-slate-100'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`
            }
          >
            Review Queue
          </NavLink>
        </div>
        <div className="p-3 border-t border-slate-800">
          <p className="text-xs text-slate-600">
            {health ? `Policy ${health.policy_version} · ${health.policy_config_sha256}` : 'Policy —'}
          </p>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 flex flex-col">
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
