// What the graph stop says, in words about the edges and parameters it concerns.
import type { FixGraphStop, Graph, GraphEdge, ScenarioParameter, ScenarioPlan, Violation } from '../../../api/types';
import { approver, nodeLabels, plural, timestamp } from '../../../lib/format';
import { RULE_CHECKS } from '../../../lib/labels';

/** Verdicts that block the graph; stop payloads also carry the checks that passed. */
export function failing(violations: Violation[] | null | undefined): Violation[] {
  return (violations ?? []).filter((v) => v.ok !== true);
}

/** Edge number in a verdict path; request errors prefix it with /body/graph. */
export function edgeIndex(path: string | null | undefined): number | null {
  const parts = (path ?? '').replace(/^\/+|\/+$/g, '').split('/');
  for (let i = 0; i + 1 < parts.length; i += 1) {
    if (parts[i] === 'edges' && /^\d+$/.test(parts[i + 1])) return Number(parts[i + 1]);
  }
  return null;
}

export function edgeFlagged(index: number, edge: GraphEdge, violations: Violation[]): boolean {
  return !edge.evidence?.length || violations.some((v) => edgeIndex(v.path) === index);
}

export function split(violations: Violation[]): { graph: Violation[]; scenario: Violation[] } {
  return {
    graph: violations.filter((v) => v.rule_id !== 'SCENARIO'),
    scenario: violations.filter((v) => v.rule_id === 'SCENARIO'),
  };
}

/** A validator verdict as a sentence about the edge it concerns. */
export function problemText(violation: Violation, graph: Graph | null | undefined): string {
  const names = nodeLabels(graph);
  const index = edgeIndex(violation.path);
  let rule = violation.rule_id ?? '';
  const message = violation.message ?? '';
  // The contract rejects an empty source list before V8 runs.
  if ((violation.path ?? '').endsWith('/evidence')) rule = 'V8';
  let what = RULE_CHECKS[rule] ?? message;
  // V3, V7 and V8 say everything in their own words; their message is for the model.
  if (!['V3', 'V7', 'V8'].includes(rule) && message && what !== message) what += ` (${message})`;
  const edge = index != null ? graph?.edges?.[index] : undefined;
  if (edge) return `Связь «${names[edge.src] ?? edge.src} → ${names[edge.dst] ?? edge.dst}»: ${what}`;
  return `Граф: ${what || 'не прошёл проверку'}`;
}

export function parameterProblem(violation: Violation, parameters: Record<string, ScenarioParameter>): string {
  const name = (violation.path ?? '').replace(/^\/macro_parameters\/?/, '');
  const owner = parameters[name]?.label;
  return owner ? `Параметр «${owner}»: ${violation.message}` : (violation.message ?? '');
}

/** One stop fires for different reasons; they must not read the same. */
export function gateWords(
  stop: FixGraphStop,
  plan: ScenarioPlan | null | undefined,
  changed: boolean,
  graphProblems: Violation[],
  scenarioProblems: Violation[],
  built: boolean,
): { title: string; text: string; quote?: string; tone: 'task' | 'problem' | 'calm' } {
  const decision = stop.decision;
  // Without a graph the checks only say its fields are missing; the stop says what to do.
  if (!built) {
    return {
      title: 'Модель не построила граф',
      text: `Ни одна из ${plural(stop.attempts ?? 0, 'попытки', 'попыток', 'попыток')} языковой модели не прошла проверку. Запустите стресс-тест заново или загрузите граф из JSON.`,
      tone: 'problem',
    };
  }
  if (decision?.outcome === 'returned') {
    return {
      title: 'Риск-менеджер вернул отчёт на доработку',
      quote: `«${decision.reason ?? ''}» — ${approver(decision.by)}, ${timestamp(decision.at)}`,
      text: 'После правки стресс-тест пересчитается и снова придёт на решение.',
      tone: 'task',
    };
  }
  if (changed && !graphProblems.length && !scenarioProblems.length) {
    return { title: 'Правки прошли проверку', text: 'Можно подтверждать и продолжать расчёт.', tone: 'calm' };
  }
  if (graphProblems.length) {
    const spent =
      !changed && (stop.attempts ?? 0) >= 3
        ? `Система трижды пыталась построить граф без ошибок — дальше только вручную. `
        : '';
    return {
      title: 'Граф не прошёл проверку',
      text: `${spent}Исправьте связи из списка ниже: откройте связь на графе или в таблице связей.`,
      tone: 'problem',
    };
  }
  if (scenarioProblems.length) {
    return {
      title: 'Сценарий нельзя рассчитать',
      text: 'Поправьте параметры сценария из списка ниже.',
      tone: 'problem',
    };
  }
  if (!plan?.confirmed && (stop.macro_parameters || stop.scenario_required)) {
    return {
      title: 'Подтвердите сценарий',
      text: 'Ошибок нет. Система предложила параметры сценария; проверьте их и граф. «Подтвердить как есть» примет их без изменений.',
      tone: 'calm',
    };
  }
  return {
    title: 'Граф построен',
    text: 'Ошибок нет, остановка сделана по просьбе при запуске. «Подтвердить как есть» примет граф и сценарий без изменений.',
    tone: 'calm',
  };
}
