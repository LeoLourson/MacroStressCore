import { factorSpec } from '../api/catalog';
import type { Graph, GraphEdge } from '../api/types';

/** Edges leading only to direct factors explain causality, without scaling shocks. */
export function descriptiveEdge(graph: Graph, edge: GraphEdge): boolean {
  const seen = new Set<string>();
  const queue = [edge.dst];
  while (queue.length) {
    const id = queue.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const next of graph.edges) if (next.src === id) queue.push(next.dst);
  }
  const targets = graph.nodes.filter((node) => seen.has(node.id) && node.kind === 'factor');
  return targets.length > 0 && targets.every((node) => {
    const spec = factorSpec(node.factor);
    return spec != null && spec.scope !== 'graph';
  });
}
