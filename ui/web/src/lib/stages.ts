// Where a stress test stands: the stages of its workflow as the server declares them
// (GET /v1/workflows, artifacts.workflow), their state for this person, and the tab a run
// opens on. A plugin agent that joins the workflow appears in its stage by itself.
import type { Artifacts, FixGraphStop, Me, RunState, RunStatus, WorkflowView } from '../api/types';
import { canApprove, canFixGraph } from '../auth/session';
import { approver, plural, positionTitle, timestamp } from './format';

export const ACTIVE: RunState[] = ['queued', 'running'];
export const FINAL: RunState[] = ['completed', 'rejected', 'failed'];

/** The stage titles of a run that has not reported its workflow yet. */
const FALLBACK: WorkflowView['stages'] = [
  { stage_id: 'event', title: 'Анализ события', nodes: [] },
  { stage_id: 'scenario', title: 'Проверка графа и сценария', nodes: [] },
  { stage_id: 'calculation', title: 'Расчёт по позициям', nodes: [] },
  { stage_id: 'portfolio', title: 'Итоги по портфелю', nodes: [] },
  { stage_id: 'decision', title: 'Решение по отчёту', nodes: [] },
];

function stagesOf(workflow: WorkflowView | null | undefined) {
  return workflow?.stages?.length ? workflow.stages : FALLBACK;
}

/** Node id -> its stage index and label, plugin agents included. */
function nodeIndex(workflow: WorkflowView | null | undefined): Map<string, { stage: number; label: string }> {
  const index = new Map<string, { stage: number; label: string }>();
  stagesOf(workflow).forEach((stage, i) => {
    for (const node of stage.nodes) index.set(node.node, { stage: i, label: node.label });
  });
  return index;
}

/** The node after a finished one, in the order the workflow lists them. */
function following(node: string, workflow: WorkflowView | null | undefined): string {
  const order = stagesOf(workflow).flatMap((stage) => stage.nodes.map((n) => n.node));
  const at = order.indexOf(node);
  if (at < 0) return node;
  // A branch node (one per position) stays the current step until all branches are done.
  const current = stagesOf(workflow).flatMap((s) => s.nodes).find((n) => n.node === node);
  if (current?.branch) return node;
  // A human stop that has been passed is followed by the automatic nodes after it.
  let next = at + 1;
  while (next < order.length && stagesOf(workflow).flatMap((s) => s.nodes)[next]?.human) next += 1;
  return order[next] ?? node;
}

/** What a running stress test is busy with, in words: «Расчёт позиции (готова LOAN-MACHINERY — …)». */
export function nowText(
  node: string | null | undefined,
  workflow: WorkflowView | null | undefined,
  names?: Record<string, string> | null,
): string {
  const [head, branch] = (node ?? '').split('/', 2);
  const index = nodeIndex(workflow);
  if (!head) return index.values().next().value?.label ?? 'Разбор события';
  if (branch) return `${index.get(head)?.label ?? head} (готова ${positionTitle(branch, names)})`;
  const next = following(head, workflow);
  return index.get(next)?.label ?? next;
}

/** The step a run stands on right now. */
export function currentStep(status: Pick<RunStatus, 'status' | 'node'>, workflow: WorkflowView | null | undefined): number {
  const stages = stagesOf(workflow);
  const index = nodeIndex(workflow);
  const stageOf = (node: string) => index.get(node)?.stage ?? 0;
  const humanStage = (kind: string) => stages.findIndex((s) => s.nodes.some((n) => n.node === kind));
  const head = (status.node ?? '').split('/')[0];
  switch (status.status) {
    case 'human_fix_graph':
      return Math.max(humanStage('human_fix_graph'), 0);
    case 'human_approval':
    case 'completed':
    case 'rejected':
      return stages.length - 1;
    case 'queued':
    case 'running':
      return head ? stageOf(following(head, workflow)) : 0;
    default:
      return stageOf(head);
  }
}

export type StepState = 'done' | 'running' | 'yours' | 'others' | 'todo' | 'failed' | 'rejected';

export interface StepView {
  title: string;
  state: StepState;
  note: string;
}

export function stopOf(status: RunStatus): FixGraphStop | null {
  const payload = status.pending_interrupt?.[0]?.payload;
  return payload && (payload as FixGraphStop).kind === 'human_fix_graph' ? (payload as FixGraphStop) : null;
}

export function steps(status: RunStatus, artifacts: Artifacts | undefined, me: Me | null): StepView[] {
  const workflow = artifacts?.workflow;
  const here = currentStep(status, workflow);
  const names = artifacts?.position_names;
  return stagesOf(workflow).map((stage, index) => {
    const title = stage.title;
    if (index < here) return { title, state: 'done', note: doneNote(stage.stage_id, artifacts) };
    if (index > here) return { title, state: 'todo', note: '' };
    switch (status.status) {
      case 'queued':
        return { title, state: 'running', note: 'В очереди' };
      case 'running':
        return { title, state: 'running', note: nowText(status.node, workflow, names) };
      case 'human_fix_graph':
        return canFixGraph(me)
          ? { title, state: 'yours', note: 'Ждёт вашей проверки' }
          : { title, state: 'others', note: 'Ждёт аналитика' };
      case 'human_approval':
        return canApprove(me)
          ? { title, state: 'yours', note: 'Ждёт вашего решения' }
          : { title, state: 'others', note: 'Ждёт риск-менеджера' };
      case 'completed':
        return {
          title,
          state: 'done',
          note: `Утверждён: ${approver(artifacts?.approved_by)}, ${timestamp(artifacts?.approved_at)}`,
        };
      case 'rejected':
        return { title, state: 'rejected', note: 'Отчёт отклонён' };
      default:
        return { title, state: 'failed', note: 'Остановлен здесь' };
    }
  });
}

function doneNote(stageId: string, artifacts: Artifacts | undefined): string {
  switch (stageId) {
    case 'event':
      return plural(artifacts?.graph?.edges?.length ?? 0, 'связь', 'связи', 'связей') + ' в графе';
    case 'scenario':
      return artifacts?.scenario?.confirmed ? 'Подтверждено аналитиком' : 'Проверка не потребовалась';
    case 'calculation':
      return plural(artifacts?.results?.length ?? 0, 'позиция', 'позиции', 'позиций');
    case 'portfolio':
      return plural(Object.keys(artifacts?.portfolio?.slices ?? {}).length, 'срез', 'среза', 'срезов');
    default:
      return '';
  }
}

export type Tab = 'scenario' | 'positions' | 'portfolio' | 'report' | 'provenance' | 'explain' | 'activity';

export const TABS: { value: Tab; title: string; empty: string }[] = [
  { value: 'scenario', title: 'Сценарий и граф', empty: '' },
  { value: 'positions', title: 'Позиции', empty: 'Появится после расчёта по позициям' },
  { value: 'portfolio', title: 'Портфель', empty: 'Появится после сведения итогов по срезам портфеля' },
  { value: 'report', title: 'Отчёт', empty: 'Появится, когда отчёт будет готов' },
  { value: 'provenance', title: 'Происхождение чисел', empty: 'Появится вместе с отчётом' },
  { value: 'explain', title: 'Вопрос по результатам', empty: 'Появится после расчёта по позициям' },
  { value: 'activity', title: 'Вызовы LLM и MCP', empty: '' },
];

export function hasReport(status: RunStatus): boolean {
  return !!status.report_url || ['human_approval', 'completed', 'rejected'].includes(status.status);
}

export function available(tab: Tab, status: RunStatus, artifacts: Artifacts | undefined): boolean {
  switch (tab) {
    case 'scenario':
    case 'activity':
      return true;
    case 'positions':
    case 'explain':
      return (artifacts?.results?.length ?? 0) > 0;
    case 'portfolio':
      return !!artifacts?.portfolio;
    default:
      return hasReport(status);
  }
}

/** Opening a run leads where this person is needed, not always to the first tab. */
export function defaultTab(status: RunStatus, artifacts: Artifacts | undefined): Tab {
  const byStage: Record<string, Tab> = { calculation: 'positions', portfolio: 'portfolio', decision: 'report' };
  switch (status.status) {
    case 'human_fix_graph':
      return 'scenario';
    case 'human_approval':
    case 'completed':
    case 'rejected':
      return 'report';
    case 'failed': {
      const stage = stagesOf(artifacts?.workflow)[currentStep(status, artifacts?.workflow)];
      const tab = byStage[stage?.stage_id ?? ''] ?? 'scenario';
      return available(tab, status, artifacts) ? tab : 'scenario';
    }
    default:
      for (const tab of ['portfolio', 'positions'] as Tab[]) {
        if (available(tab, status, artifacts)) return tab;
      }
      return 'scenario';
  }
}
