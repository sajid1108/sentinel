import { ACTION_BORDER, ACTION_LABEL, ACTION_TEXT, ACTION_TINT, type Action } from '../lib/actions'

/** The one place an action is rendered as a badge, so its §11b colour is never chosen twice. */
export function ActionBadge({ action, size = 'md' }: { action: Action; size?: 'sm' | 'md' | 'lg' }) {
  const sizing =
    size === 'lg'
      ? 'text-xl font-semibold px-4 py-2'
      : size === 'sm'
        ? 'text-xs font-medium px-2 py-0.5'
        : 'text-sm font-medium px-2.5 py-1'
  return (
    <span
      data-action={action}
      className={`inline-flex items-center rounded border tracking-tight ${sizing} ${ACTION_TINT[action]} ${ACTION_BORDER[action]} ${ACTION_TEXT[action]}`}
    >
      {ACTION_LABEL[action]}
    </span>
  )
}
