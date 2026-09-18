/** §Non-negotiable 18: the limitation sentence, verbatim, on every page. */
export const DATA_NOTICE =
  'Synthetic data is used to validate the architecture, policy behaviour, auditability, and ' +
  'coordinated-pattern detection. Real deployment would require merchant-specific historical data and ' +
  'prospective validation.'

export function SyntheticDataBanner() {
  return (
    <div className="border-b border-amber-500/30 bg-amber-900/30 px-4 py-2 text-center text-sm text-amber-200">
      {DATA_NOTICE}
    </div>
  )
}
