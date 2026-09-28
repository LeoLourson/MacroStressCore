import { Box, Group, Text } from '@mantine/core';
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
} from '@xyflow/react';
import { useMemo } from 'react';
import { factorLabel } from '../../../api/catalog';
import type { Graph, GraphNode, NodeKind } from '../../../api/types';
import { elasticityText, nodeName } from '../../../lib/format';
import { NODE_KINDS } from '../../../lib/labels';
import { descriptiveEdge } from '../../../lib/graph';

const COLUMNS: NodeKind[] = ['event', 'channel', 'sector', 'factor'];
const COLUMN_WIDTH = 300;
const NODE_WIDTH = 220;
const ROW_HEIGHT = 78;

const TONE: Record<NodeKind, { bg: string; border: string }> = {
  event: { bg: 'var(--mantine-color-gray-1)', border: 'var(--mantine-color-gray-5)' },
  channel: { bg: 'var(--mantine-color-steel-0)', border: 'var(--mantine-color-steel-3)' },
  sector: { bg: 'white', border: 'var(--mantine-color-gray-4)' },
  factor: { bg: 'white', border: 'var(--mantine-color-gray-4)' },
};

type CardData = { node: GraphNode };

function caption(node: GraphNode): string {
  switch (node.kind) {
    case 'sector':
      return `ОКВЭД ${node.okved ?? '—'}`;
    case 'factor': {
      const factor = factorLabel(node.factor);
      if (node.key) return `${factor} · ${node.key}`;
      return factor.toLowerCase() === node.label.toLowerCase() ? 'Фактор модели' : factor;
    }
    case 'event':
      return nodeName(node) === 'Событие' ? 'Источник всех шоков' : 'Событие';
    default:
      return 'Канал влияния';
  }
}

function Card({ data }: NodeProps<Node<CardData>>) {
  const { node } = data;
  const tone = TONE[node.kind];
  return (
    <Box
      w={NODE_WIDTH}
      px="sm"
      py={6}
      style={{ background: tone.bg, border: `1px solid ${tone.border}`, borderRadius: 8 }}
    >
      {node.kind !== 'event' && <Handle type="target" position={Position.Left} isConnectable={false} />}
      <Text size="sm" fw={500} lineClamp={2} lh={1.3}>
        {nodeName(node)}
      </Text>
      <Text size="xs" c="dimmed" lineClamp={1}>
        {caption(node)}
      </Text>
      {node.kind !== 'factor' && <Handle type="source" position={Position.Right} isConnectable={false} />}
    </Box>
  );
}

const nodeTypes = { card: Card };

export function edgeCaption(sign: 1 | -1, text: string, lag: number): string {
  return `${sign === 1 ? '+' : '−'}${text}${lag ? ` · ${lag} мес.` : ''}`;
}

/** The transmission graph in four columns: event → channels → sectors → the models' factors. */
export function GraphCanvas({
  graph,
  flagged,
  selected,
  onSelect,
}: {
  graph: Graph;
  flagged: Set<number>;
  selected: number | null;
  onSelect: (index: number) => void;
}) {
  const { nodes, edges, height } = useMemo(() => {
    const columns = COLUMNS.map((kind) => graph.nodes.filter((n) => n.kind === kind));
    const rows = Math.max(1, ...columns.map((c) => c.length));
    const placed: Node<CardData>[] = columns.flatMap((column, x) =>
      column.map((node, y) => ({
        id: node.id,
        type: 'card',
        position: {
          x: x * COLUMN_WIDTH,
          y: (y + (rows - column.length) / 2) * ROW_HEIGHT,
        },
        data: { node },
        draggable: false,
        selectable: false,
      })),
    );
    const lines: Edge[] = graph.edges.map((edge, index) => {
      const problem = flagged.has(index);
      const active = selected === index;
      const color = active
        ? 'var(--mantine-color-steel-7)'
        : problem
          ? 'var(--mantine-color-orange-8)'
          : 'var(--mantine-color-gray-6)';
      return {
        id: `e${index}`,
        source: edge.src,
        target: edge.dst,
        // A direct shock's size is in the scenario, not on the arrow: only a problem marks it.
        label: descriptiveEdge(graph, edge)
          ? problem
            ? '⚠'
            : undefined
          : `${problem ? '⚠ ' : ''}${edgeCaption(edge.sign, elasticityText(edge.elasticity), edge.lag_months)}`,
        labelStyle: { fontSize: 11, fill: 'var(--mantine-color-dark-6)' },
        labelBgStyle: { fill: 'white' },
        labelBgPadding: [4, 2],
        style: {
          stroke: color,
          strokeWidth: active || problem ? 2.5 : 1.4,
          strokeDasharray: problem ? '6 4' : undefined,
          cursor: 'pointer',
        },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        interactionWidth: 18,
      };
    });
    return { nodes: placed, edges: lines, height: Math.min(640, Math.max(300, rows * ROW_HEIGHT + 80)) };
  }, [graph, flagged, selected]);

  return (
    <Box>
      <Group gap="xl" mb={6} px={4} wrap="nowrap" style={{ overflow: 'hidden' }}>
        {COLUMNS.map((kind) => (
          <Text key={kind} size="xs" c="dimmed" fw={600} tt="uppercase" w={COLUMN_WIDTH - 32}>
            {NODE_KINDS[kind]}
          </Text>
        ))}
      </Group>
      <Box h={height} style={{ border: '1px solid var(--mantine-color-gray-3)', borderRadius: 8 }} bg="white">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onEdgeClick={(_, edge) => onSelect(Number(edge.id.slice(1)))}
          fitView
          fitViewOptions={{ padding: 0.08 }}
          minZoom={0.3}
          maxZoom={1.6}
          nodesConnectable={false}
          nodesDraggable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} color="var(--mantine-color-gray-2)" />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </Box>
      <Text size="xs" c="dimmed" mt={6}>
        На стрелках: знак (+ усиливает, − ослабляет), сила связи (эластичность) и задержка. Связи с
        проблемами — пунктиром со знаком ⚠. Нажмите на стрелку, чтобы открыть связь и её источники.
        Стрелка без подписи ведёт к фактору прямого шока; его величина задаётся в сценарии.
      </Text>
    </Box>
  );
}
