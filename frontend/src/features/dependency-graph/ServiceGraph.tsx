import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";

import { STATUS_STYLES, cx } from "../../components/ui";
import type { GraphEdge, GraphNode, NodeStatus } from "../../types/api";

export interface GraphNodeData extends Record<string, unknown> {
  node: GraphNode;
  status: NodeStatus;
  selected: boolean;
  pulse: boolean;
}

function ServiceNodeView({ data }: NodeProps<Node<GraphNodeData>>) {
  const { node, status, selected, pulse } = data;
  const style = STATUS_STYLES[status];
  return (
    <div
      className={cx(
        "w-48 rounded-xl border-2 bg-white px-3 py-2 shadow-sm transition-colors",
        style.ring,
        node.kind === "inferred" && "border-dashed",
        selected && "ring-2 ring-accent-500 ring-offset-2",
        pulse && "ring-2 ring-red-300",
      )}
      data-testid={`graph-node-${node.id}`}
      data-status={status}
    >
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-slate-300" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-slate-900" title={node.id}>
          {node.id}
        </span>
        {node.hypothesis_rank !== null && (
          <span className="rounded bg-accent-600 px-1.5 text-[10px] font-semibold text-white" title={`Hypothesis #${node.hypothesis_rank}, heuristic score ${node.hypothesis_score?.toFixed(2)}`}>
            #{node.hypothesis_rank}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-600">
        <span className={cx("h-2 w-2 rounded-full", style.dot)} aria-hidden />
        {style.label}
        {node.kind === "inferred" && <span className="text-slate-400">· inferred</span>}
      </div>
      <div className="mt-1 text-[11px] text-slate-500 tabular-nums">
        {node.kind === "observed" ? `${node.error_count}/${node.event_count} err` : "no own events"}
        {node.p95_ms !== null && ` · p95 ${Math.round(node.p95_ms)} ms`}
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-slate-300" />
    </div>
  );
}

const nodeTypes = { service: ServiceNodeView };

/** Deterministic layered layout: rows by dependency depth, columns by name within a row. */
export function layout(nodes: GraphNode[]): Record<string, { x: number; y: number }> {
  const maxDepth = Math.max(0, ...nodes.map((n) => n.depth ?? 0));
  const layers = new Map<number, GraphNode[]>();
  for (const node of [...nodes].sort((a, b) => a.id.localeCompare(b.id))) {
    const depth = node.depth ?? maxDepth + 1;
    layers.set(depth, [...(layers.get(depth) ?? []), node]);
  }
  const positions: Record<string, { x: number; y: number }> = {};
  for (const [depth, members] of layers) {
    members.forEach((node, index) => {
      positions[node.id] = { x: (index - (members.length - 1) / 2) * 230, y: depth * 130 };
    });
  }
  return positions;
}

export function ServiceGraph({
  nodes,
  edges,
  statusOverride,
  activeEdge,
  selectedId,
  onSelectNode,
  onSelectEdge,
  height = 520,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  statusOverride?: Record<string, NodeStatus>;
  activeEdge?: { id: string; failed: boolean } | null;
  selectedId?: string | null;
  onSelectNode?: (id: string) => void;
  onSelectEdge?: (id: string) => void;
  height?: number;
}) {
  const positions = useMemo(() => layout(nodes), [nodes]);
  const flowNodes = useMemo<Node<GraphNodeData>[]>(
    () =>
      nodes.map((node) => ({
        id: node.id,
        type: "service",
        position: positions[node.id] ?? { x: 0, y: 0 },
        data: {
          node,
          status: statusOverride?.[node.id] ?? node.status,
          selected: selectedId === node.id,
          pulse: activeEdge?.failed === true && activeEdge.id.endsWith(`->${node.id}`),
        },
        draggable: true,
      })),
    [nodes, positions, statusOverride, selectedId, activeEdge],
  );
  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((edge) => {
        const failing = (edge.error_rate ?? 0) >= 0.2 && edge.error_count >= 3;
        const active = activeEdge?.id === edge.id;
        const color = active ? (activeEdge?.failed ? "#dc2626" : "#4f46e5") : failing ? "#ef4444" : "#94a3b8";
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          animated: active || failing,
          label: statusOverride ? undefined : `${edge.call_count} calls${edge.error_count ? ` · ${edge.error_count} err` : ""}`,
          labelStyle: { fontSize: 10, fill: "#475569" },
          labelBgStyle: { fill: "#ffffff" },
          style: { stroke: color, strokeWidth: active ? 3 : failing ? 2 : 1.25, strokeDasharray: edge.in_cycle ? "6 3" : undefined },
          markerEnd: { type: MarkerType.ArrowClosed, color },
        };
      }),
    [edges, activeEdge, statusOverride],
  );

  return (
    <div style={{ height }} className="rounded-xl border border-slate-200 bg-slate-50" role="figure" aria-label="Service dependency graph">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.12, maxZoom: 1.1 }}
        minZoom={0.3}
        onNodeClick={(_, node) => onSelectNode?.(node.id)}
        onEdgeClick={(_, edge) => onSelectEdge?.(edge.id)}
      >
        <Background gap={18} color="#e2e8f0" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
