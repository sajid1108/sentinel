/**
 * The relationship graph (B4), drawn with @xyflow/react at the server's coordinates.
 *
 * The frontend never runs a layout (§11b): every node's x and y come from the payload, the graph is not
 * draggable, connectable or selectable, and the only controls are zoom and fit. Node shape is by `kind`,
 * node colour by `state` (red is only ever a confirmed-abuse node), and an edge is dashed exactly when
 * `counted_as_evidence` is false, with the server's `discount_reason` on hover. Labels are the server's
 * masked strings; no identifier hash exists in the payload to leak.
 */
import { useEffect, useMemo, useRef } from 'react'
import {
  Background,
  Controls,
  Position,
  ReactFlow,
  getStraightPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type { components } from '../api/types'

type GraphNodeData = components['schemas']['GraphNode']
type GraphEdgeData = components['schemas']['GraphEdge']
type GraphPayload = components['schemas']['GraphPayload']

const FLAG_LABEL: Record<string, string> = {
  MULTI_TENANT: 'Multi-tenant',
  SEQUENTIAL_DEVICE: 'Sequential device',
  HIGH_FANOUT: 'High fanout',
  RECENT_24H: 'Last 24 h',
}

const KIND_LABEL: Record<GraphNodeData['kind'], string> = {
  ACCOUNT: 'Account',
  ORDER: 'Order',
  DEVICE: 'Device',
  ADDRESS: 'Address',
  PAYMENT_TOKEN: 'Payment token',
}

/** Outline and fill by state. `red-500` appears here and nowhere else in the graph. */
function stateStyle(state: GraphNodeData['state']): { border: string; background: string; text: string } {
  switch (state) {
    case 'CURRENT':
      return { border: 'var(--color-verified)', background: 'rgba(15,23,42,0.95)', text: '#f1f5f9' }
    case 'CONFIRMED_ABUSE':
      return { border: 'var(--color-block)', background: 'var(--color-block)', text: '#0f172a' }
    case 'LINKED':
      return { border: '#64748b', background: '#1e293b', text: '#e2e8f0' }
    default:
      return { border: '#334155', background: '#0f172a', text: '#94a3b8' }
  }
}

/** Shape by kind (B4): ACCOUNT circle, DEVICE square, ADDRESS diamond, TOKEN rounded rect, ORDER dot. */
function shapeStyle(kind: GraphNodeData['kind'], current: boolean): React.CSSProperties {
  const size = current ? 76 : 56
  switch (kind) {
    case 'ACCOUNT':
      return { width: size, height: size, borderRadius: '9999px' }
    case 'DEVICE':
      return { width: 52, height: 52, borderRadius: 2 }
    case 'ADDRESS':
      return { width: 46, height: 46, borderRadius: 2, transform: 'rotate(45deg)' }
    case 'PAYMENT_TOKEN':
      return { width: 74, height: 40, borderRadius: 12 }
    default:
      return { width: current ? 26 : 18, height: current ? 26 : 18, borderRadius: '9999px' }
  }
}

type FlowNodeData = { graph: GraphNodeData }

function SentinelNode({ data }: NodeProps<Node<FlowNodeData>>) {
  const node = data.graph
  const current = node.state === 'CURRENT'
  const colours = stateStyle(node.state)
  const shape = shapeStyle(node.kind, current)
  return (
    <div className="relative flex flex-col items-center" data-testid="graph-node" data-node-state={node.state}>
      <div
        title={`${KIND_LABEL[node.kind]} · ${node.label}`}
        style={{
          ...shape,
          border: `${current ? 3 : 2}px solid ${colours.border}`,
          background: colours.background,
          boxShadow: current ? `0 0 0 4px color-mix(in oklab, ${colours.border} 25%, transparent)` : undefined,
        }}
      />
      <span
        className="mt-1 max-w-[140px] truncate text-center text-[10px]"
        style={{ color: current ? '#f1f5f9' : '#cbd5e1' }}
      >
        {node.label}
      </span>
      {node.flags.length > 0 && (
        <span className="mt-0.5 flex flex-wrap justify-center gap-0.5">
          {node.flags.map((flag) => (
            <span
              key={flag}
              data-testid="graph-flag"
              className="rounded-sm border border-slate-600 bg-slate-800 px-1 text-[9px] text-slate-300"
            >
              {FLAG_LABEL[flag] ?? flag}
            </span>
          ))}
        </span>
      )}
    </div>
  )
}

const NODE_TYPES = { sentinel: SentinelNode }

function LegendSwatch({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <li className="flex items-center gap-2">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center">{children}</span>
      <span className="text-[11px] text-slate-400">{label}</span>
    </li>
  )
}

export function GraphLegend() {
  const box = (style: React.CSSProperties) => (
    <span style={{ border: '2px solid #64748b', background: '#1e293b', ...style }} />
  )
  return (
    <div data-testid="graph-legend" className="rounded border border-slate-800 bg-slate-950 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Legend</h3>
      <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5">
        <LegendSwatch label="Account">{box({ width: 16, height: 16, borderRadius: 9999 })}</LegendSwatch>
        <LegendSwatch label="Device">{box({ width: 15, height: 15, borderRadius: 2 })}</LegendSwatch>
        <LegendSwatch label="Address">
          {box({ width: 13, height: 13, borderRadius: 2, transform: 'rotate(45deg)' })}
        </LegendSwatch>
        <LegendSwatch label="Payment token">{box({ width: 22, height: 12, borderRadius: 6 })}</LegendSwatch>
        <LegendSwatch label="Order">{box({ width: 9, height: 9, borderRadius: 9999 })}</LegendSwatch>
        <LegendSwatch label="This order’s account">
          <span
            style={{
              width: 16,
              height: 16,
              borderRadius: 9999,
              border: '2px solid var(--color-verified)',
              background: '#0f172a',
            }}
          />
        </LegendSwatch>
        <LegendSwatch label="Confirmed abuse">
          <span
            style={{
              width: 16,
              height: 16,
              borderRadius: 9999,
              border: '2px solid var(--color-block)',
              background: 'var(--color-block)',
            }}
          />
        </LegendSwatch>
        <LegendSwatch label="Linked, no confirmation">
          {box({ width: 16, height: 16, borderRadius: 9999 })}
        </LegendSwatch>
        <LegendSwatch label="Counted as evidence">
          <svg width="24" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="24" y2="3" stroke="#64748b" strokeWidth="2" />
          </svg>
        </LegendSwatch>
        <LegendSwatch label="Discounted — not counted (hover for why)">
          <svg width="24" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="24" y2="3" stroke="#64748b" strokeWidth="2" strokeDasharray="4 3" />
          </svg>
        </LegendSwatch>
      </ul>
    </div>
  )
}

/**
 * Each node's box and its connection points, declared rather than measured. The server already decided
 * where every node goes, so measurement would only make the drawing depend on the browser having laid the
 * page out first - the edges would appear a frame late, and differently under a different font. Declaring
 * one source and one target handle at the node's centre makes every edge a straight line between centres,
 * identical in every environment.
 */
const NODE_BOX: Record<GraphNodeData['kind'], { width: number; height: number }> = {
  ACCOUNT: { width: 76, height: 76 },
  DEVICE: { width: 52, height: 52 },
  ADDRESS: { width: 46, height: 46 },
  PAYMENT_TOKEN: { width: 74, height: 40 },
  ORDER: { width: 26, height: 26 },
}

function centreHandles(box: { width: number; height: number }): Node<FlowNodeData>['handles'] {
  const at = { x: box.width / 2, y: box.height / 2, width: 0, height: 0 }
  return [
    { id: null, type: 'source', position: Position.Bottom, ...at },
    { id: null, type: 'target', position: Position.Top, ...at },
  ]
}

function toFlowNode(node: GraphNodeData): Node<FlowNodeData> {
  const box = NODE_BOX[node.kind]
  // The server's coordinates are node centres; React Flow places a node by its top-left corner.
  return {
    id: node.id,
    type: 'sentinel',
    position: { x: node.x - box.width / 2, y: node.y - box.height / 2 },
    data: { graph: node },
    draggable: false,
    selectable: false,
    connectable: false,
    width: box.width,
    height: box.height,
    measured: box,
    handles: centreHandles(box),
  }
}

type FlowEdgeData = { graph: GraphEdgeData }

/**
 * A straight edge carrying an SVG <title>, so hovering a dashed edge shows the server's discount reason
 * as a native tooltip without adding a tooltip library.
 */
function SentinelEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<FlowEdgeData>>) {
  const edge = data?.graph
  const dashed = edge ? !edge.counted_as_evidence : false
  const [path] = getStraightPath({ sourceX, sourceY, targetX, targetY })
  const tooltip = dashed
    ? `Not counted as evidence: ${edge?.discount_reason ?? 'discounted link'}`
    : `Counted as evidence (weight ${edge?.decayed_weight ?? 0})`
  return (
    <g data-testid="graph-edge" data-edge-id={id} data-counted={String(!dashed)}>
      <title>{tooltip}</title>
      <path
        d={path}
        fill="none"
        stroke={dashed ? '#475569' : '#64748b'}
        strokeWidth={dashed ? 1.5 : 2}
        strokeDasharray={dashed ? '5 4' : undefined}
      />
      {/* a wider invisible path so the tooltip is easy to hit */}
      <path d={path} fill="none" stroke="transparent" strokeWidth={12} />
    </g>
  )
}

const EDGE_TYPES = { sentinel: SentinelEdge }

function toFlowEdge(edge: GraphEdgeData): Edge<FlowEdgeData> {
  return {
    id: edge.id,
    type: 'sentinel',
    source: edge.source,
    target: edge.target,
    animated: false,
    data: { graph: edge },
  }
}

const FIT_PADDING = 0.06

type Fittable = { fitView: (options?: { padding?: number }) => void }

export function RelationshipGraph({ graph, height = 580 }: { graph: GraphPayload; height?: number }) {
  const nodes = useMemo(() => graph.nodes.map(toFlowNode), [graph.nodes])
  const edges = useMemo(() => graph.edges.map(toFlowEdge), [graph.edges])
  const signature = useMemo(() => graph.nodes.map((node) => node.id).join('|'), [graph.nodes])
  const flow = useRef<Fittable | null>(null)

  /**
   * Fit the whole graph on load and whenever it changes. React Flow's own `fitView` prop waits for
   * `nodesInitialized`, which needs handle bounds measured from the DOM; this graph declares its handles
   * instead (see NODE_BOX), so the fit is driven from here against the positions the server gave.
   */
  useEffect(() => {
    const frame = requestAnimationFrame(() => flow.current?.fitView({ padding: FIT_PADDING }))
    return () => cancelAnimationFrame(frame)
  }, [signature])

  if (graph.nodes.length === 0) {
    return (
      <div
        data-testid="graph-empty"
        style={{ height }}
        className="flex items-center justify-center rounded border border-slate-800 bg-slate-950 text-sm text-slate-400"
      >
        No relationship data was captured for this decision.
      </div>
    )
  }

  return (
    <div data-testid="relationship-graph" style={{ height }} className="rounded border border-slate-800 bg-slate-950">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        fitView
        fitViewOptions={{ padding: FIT_PADDING }}
        minZoom={0.1}
        onInit={(instance) => {
          flow.current = instance
        }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1e293b" gap={24} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  )
}

export { FLAG_LABEL }
