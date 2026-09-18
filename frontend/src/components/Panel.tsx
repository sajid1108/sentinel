import type { ReactNode } from 'react'

/** A surface. One definition so every panel on the page shares the §11b border and background. */
export function Panel({
  title,
  subtitle,
  right,
  children,
  className = '',
}: {
  title?: string
  subtitle?: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-lg border border-slate-800 bg-slate-900 ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-4 border-b border-slate-800 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold tracking-wide text-slate-100">{title}</h2>}
            {subtitle && <div className="mt-0.5 text-xs text-slate-400">{subtitle}</div>}
          </div>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-200">{children}</dd>
    </div>
  )
}

/**
 * Loading placeholder shaped like the block it replaces (§D): no spinner, no layout shift, and no
 * animation - §A.7 allows only short hover and focus transitions.
 */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`rounded bg-slate-800 ${className}`} aria-hidden="true" />
}
