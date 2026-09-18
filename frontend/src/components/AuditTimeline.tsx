/**
 * Audit timeline (B6), oldest first, with the chain-integrity badge from GET /audit-events/verify.
 * Every line is read from the recorded event: nothing is inferred, and the reason text of an override is
 * shown as the reviewer wrote it.
 */
import type { components } from '../api/types'
import type { AuditVerifyResponse } from '../api/client'
import { ACTION_LABEL, REASON_LABEL, type Action } from '../lib/actions'
import { formatTimestamp, hashPrefix } from '../lib/format'
import { Panel } from './Panel'

/** Actions and override reasons read as labels, not as enum values (Phase 9 brief 1.6). */
function actionLabel(action: Action): string {
  return ACTION_LABEL[action] ?? action
}

type AuditEventOut = components['schemas']['AuditEventOut']

const EVENT_LABEL: Record<AuditEventOut['event_type'], string> = {
  DECISION_CREATED: 'Decision created',
  OVERRIDE_APPLIED: 'Override applied',
  APPEAL_OPENED: 'Appeal opened',
}

type OverridePayload = { reason_category?: string; reason_text?: string }
type AppealPayload = { appeal_reference?: string; channel?: string; status?: string }

function overrideOf(event: AuditEventOut): OverridePayload | null {
  const value = (event.payload as { override?: unknown }).override
  return value && typeof value === 'object' ? (value as OverridePayload) : null
}

function appealOf(event: AuditEventOut): AppealPayload | null {
  const value = (event.payload as { appeal?: unknown }).appeal
  return value && typeof value === 'object' ? (value as AppealPayload) : null
}

function ChainBadge({ verify }: { verify: AuditVerifyResponse | null }) {
  if (verify === null) {
    return <span className="text-xs text-slate-500">Checking the chain…</span>
  }
  if (verify.valid) {
    return (
      <span
        data-testid="chain-badge"
        className="rounded border border-verified/60 bg-verified/10 px-2 py-0.5 text-xs font-medium text-verified"
      >
        Chain verified ✓
      </span>
    )
  }
  return (
    <span
      data-testid="chain-badge"
      className="rounded border border-block/60 bg-block/10 px-2 py-0.5 text-xs font-medium text-block-text"
    >
      Chain broken at event {verify.first_broken_seq}
    </span>
  )
}

export function AuditTimeline({
  events,
  verify,
}: {
  events: AuditEventOut[]
  verify: AuditVerifyResponse | null
}) {
  const ordered = events.slice().sort((a, b) => a.seq - b.seq)
  return (
    <Panel title="Audit timeline" right={<ChainBadge verify={verify} />}>
      <ol data-testid="audit-timeline" className="space-y-3">
        {ordered.map((event) => {
          const override = overrideOf(event)
          const appeal = appealOf(event)
          return (
            <li
              key={event.event_id}
              data-testid="audit-event"
              data-event-type={event.event_type}
              className="border-l-2 border-slate-800 pl-3"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <span className="text-sm text-slate-100">{EVENT_LABEL[event.event_type]}</span>
                <span className="text-xs text-slate-400">
                  {event.actor_type === 'SYSTEM' ? 'System' : event.actor_id}
                </span>
                <span className="text-xs text-slate-500">{formatTimestamp(event.occurred_at)}</span>
              </div>
              <p className="mt-0.5 text-xs text-slate-300">
                {event.previous_action
                  ? `${actionLabel(event.previous_action)} → ${actionLabel(event.new_action)}`
                  : actionLabel(event.new_action)}
              </p>
              {override && (
                <p className="mt-0.5 text-xs text-slate-400">
                  <span className="text-slate-300">
                    {override.reason_category
                      ? (REASON_LABEL[override.reason_category] ?? override.reason_category)
                      : ''}
                  </span>
                  {override.reason_text ? ` — ${override.reason_text}` : ''}
                </p>
              )}
              {appeal && (
                <p className="mt-0.5 text-xs text-slate-400">
                  {appeal.appeal_reference} · {appeal.channel} · {appeal.status}
                </p>
              )}
              <p className="mt-0.5 font-mono text-[10px] text-slate-600">
                {hashPrefix(event.event_hash, 10)}
              </p>
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}
