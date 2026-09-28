// Where a stress test stands: the stages of its workflow as the server declares them
// (GET /v1/workflows, artifacts.workflow), their state for this person, and the tab a run
// opens on. A plugin agent that joins the workflow appears in its stage by itself.
import type { Artifacts, FixGraphStop, LlmWaiting, Me, RunState, RunStatus, WorkflowView } from '../api/types';
import { canApprove, canFixGraph } from '../auth/session';
import { approver, plural, timestamp } from './format';

export const ACTIVE: RunState[] = ['queued', 'running'];
export const FINAL: RunState[] = ['completed', 'rejected', 'failed'];

/** The stage titles of a run that has not reported its workflow yet. */
const FALLBACK: WorkflowView['stages'] = [
  { stage_id: 'event', title: 'Анализ события', nodes: [] },
  { stage_id: 'scenario', title: 'Проверка графа и сценария', nodes: [] },
  { stage_id: 'calculation', title: 'Расчёт по позициям', nodes: [] },
  { stage_id: 'portfolio', title: 'Итоги по портфелю', nodes: [] },
  { stage_id: 'report', title: 'Написание отчёта', nodes: [] },
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

/**
 * The node a running stress test is on: the first node the server says it starts next that
 * the workflow shows, else the last one it finished. Only the server knows which way a route
 * turns: a graph that fails its check goes back to the model, not on to the calculation.
 */
function runningNode(status: Pick<RunStatus, 'node' | 'next'>, workflow: WorkflowView | null | undefined): string {
  const index = nodeIndex(workflow);
  return status.next?.find((node) => index.has(node)) ?? (status.node ?? '').split('/')[0];
}

/** What a running stress test is busy with, in words: «Построение графа влияния». */
export function nowText(status: Pick<RunStatus, 'node' | 'next'>, workflow: WorkflowView | null | undefined): string {
  const index = nodeIndex(workflow);
  return index.get(runningNode(status, workflow))?.label ?? index.values().next().value?.label ?? 'Разбор события';
}

/** The step a run stands on right now. */
export function currentStep(status: Pick<RunStatus, 'status' | 'node' | 'next'>, workflow: WorkflowView | null | undefined): number {
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
      return stageOf(runningNode(status, workflow));
    default:
      return stageOf(head);
  }
}

/** What the language model is busy with, in words: «пишет текст отчёта». */
export function llmDoing(waiting: LlmWaiting): string {
  if (waiting.purpose === 'repair') return 'исправляет свой ответ';
  switch (waiting.schema) {
    case 'CausalOutput':
      return 'строит граф влияния и сценарий';
    case 'AdvisoryNarrative':
      return 'пишет текст отчёта';
    case 'tools':
      return 'отвечает на вопрос по результатам';
    default:
      return 'готовит ответ';
  }
}

export type StepState = 'done' | 'running' | 'yours' | 'others' | 'todo' | 'failed' | 'rejected';

export interface StepView {
  title: string;
  state: StepState;
  note: string;
  /** While the model answers: when it started, for a live timer beside the note. */
  since?: string;
}

export function stopOf(status: RunStatus): FixGraphStop | null {
  const payload = status.pending_interrupt?.[0]?.payload;
  return payload && (payload as FixGraphStop).kind === 'human_fix_graph' ? (payload as FixGraphStop) : null;
}

export function steps(status: RunStatus, artifacts: Artifacts | undefined, me: Me | null): StepView[] {
  const workflow = artifacts?.workflow;
  const here = currentStep(status, workflow);
  return stagesOf(workflow).map((stage, index) => {
    const title = stage.title;
    // The model answered, but no answer passed the checks: the analysis did not succeed.
    if (index < here && stage.stage_id === 'event' && !artifacts?.graph?.nodes?.length) {
      return { title, state: 'failed', note: 'Граф не построен' };
    }
    if (index < here) return { title, state: 'done', note: doneNote(stage.stage_id, artifacts) };
    if (index > here) return { title, state: 'todo', note: '' };
    switch (status.status) {
      case 'queued':
        return { title, state: 'running', note: 'В очереди' };
      case 'running': {
        // The step is the one place that shows the run is working: what the model writes, and for how long.
        const waiting = status.llm_waiting;
        return waiting
          ? { title, state: 'running', note: `LLM ${llmDoing(waiting)}`, since: waiting.started_at }
          : { title, state: 'running', note: nowText(status, workflow) };
      }
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
    case 'report':
      return 'Отчёт готов';
    default:
      return '';
  }
}

export type Tab = 'scenario' | 'positions' | 'portfolio' | 'report' | 'provenance' | 'explain' | 'activity';

export const TABS: { value: Tab; title: string; empty: string }[] = [
  { value: 'scenario', title: 'Сценарий и граф', empty: '' },
  { value: 'positions', title: 'Позиции', empty: 'Появится после расчёта по позициям' },
  { value: 'portfolio', title: 'Портфель', empty: 'Появится после сведения итогов по срезам портфеля' },
  { value: 'report', title: 'Отчёт', empty: 'Появится, когда отчёт будет написан' },
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
  const byStage: Record<string, Tab> = { calculation: 'positions', portfolio: 'portfolio', report: 'portfolio', decision: 'report' };
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
