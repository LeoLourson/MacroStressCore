import { FieldHelp } from '../../../components/FieldHelp';
import { Alert, Button, Group, Modal, NumberInput, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { IconTrash, IconAlertTriangle } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { directFactors, factorSpec, graphFactors } from '../../../api/catalog';
import type { Graph, ScenarioKind, ScenarioParameter } from '../../../api/types';
import { scenarioValue } from '../../../lib/format';
import { SCENARIO_KINDS } from '../../../lib/labels';

const FIELDS: Record<ScenarioKind, [keyof ScenarioParameter, string][]> = {
  point: [['value', 'Значение']],
  triangular: [
    ['low', 'Минимум'],
    ['mode', 'Наиболее вероятное'],
    ['high', 'Максимум'],
  ],
  uniform: [
    ['low', 'Минимум'],
    ['high', 'Максимум'],
  ],
  truncated_normal: [
    ['mean', 'Среднее'],
    ['sigma', 'Разброс (σ)'],
    ['low', 'Минимум'],
    ['high', 'Максимум'],
  ],
};

/** A parameter without a factor replaces a model input (a demand elasticity) instead of shocking one. */
export function isStructural(_name: string, parameter: ScenarioParameter): boolean {
  return !parameter.factor && !parameter.channel;
}

export function channelsOf(graph: Graph | null | undefined): Record<string, string> {
  return Object.fromEntries((graph?.nodes ?? []).filter((n) => n.kind === 'channel').map((n) => [n.id, n.label]));
}

/** Why a parameter cannot be drawn, before the server is asked. */
export function parameterError(p: ScenarioParameter): string | null {
  const v = (x: number | undefined) => x ?? Number.NaN;
  if (p.factor && factorSpec(p.factor)?.scope !== 'graph' && !p.key?.trim()) {
    return 'Укажите ключ: к каким инструментам применяется фактор.';
  }
  switch (p.kind) {
    case 'triangular':
      if (!(v(p.low) <= v(p.mode) && v(p.mode) <= v(p.high) && v(p.low) < v(p.high)))
        return 'Нужно: минимум ≤ наиболее вероятное ≤ максимум, и минимум меньше максимума.';
      return null;
    case 'uniform':
    case 'truncated_normal':
      if (!(v(p.low) < v(p.high))) return 'Минимум должен быть меньше максимума.';
      if (p.kind === 'truncated_normal' && !(v(p.sigma) > 0)) return 'Разброс должен быть больше нуля.';
      return null;
    default:
      return Number.isFinite(v(p.value)) ? null : 'Укажите значение.';
  }
}

function unitOf(factorId: string | null): ScenarioParameter['unit'] {
  return factorSpec(factorId)?.unit ?? 'fraction';
}

export function newParameter(
  parameters: Record<string, ScenarioParameter>,
  graph: Graph,
  factors: Record<string, string[]>,
): [string, ScenarioParameter] {
  const channel = Object.keys(channelsOf(graph))[0] ?? null;
  const missing = graph.nodes.find((node) => node.kind === 'factor' && node.key &&
    !Object.values(parameters).some((p) => p.factor === node.factor && p.key === node.key));
  const factor = missing?.factor ?? (channel && factors[channel]?.[0]) ?? graphFactors()[0]?.factor_id ?? null;
  let index = Object.keys(parameters).length + 1;
  while (`parameter_${index}` in parameters) index += 1;
  return [
    `parameter_${index}`,
    {
      label: `Новый параметр ${index}`,
      kind: 'point',
      value: 0,
      unit: unitOf(factor),
      channel: missing ? null : channel,
      factor,
      key: missing?.key ?? null,
      evidence: [],
    },
  ];
}

/** Editing one shock of the scenario; shares and log returns are entered in percent, delays in days. */
export function ParameterModal({
  name,
  parameter,
  graph,
  factors,
  onClose,
  onSave,
  onDelete,
}: {
  name: string | null;
  parameter: ScenarioParameter | null;
  graph: Graph;
  /** Channel -> the graph factors it reaches. */
  factors: Record<string, string[]>;
  onClose: () => void;
  onSave: (parameter: ScenarioParameter) => void;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState<ScenarioParameter | null>(parameter);
  useEffect(() => setDraft(parameter), [parameter]);
  if (!name || !draft) return <Modal opened={false} onClose={onClose} />;

  const structural = isStructural(name, draft);
  const direct = !!draft.factor && factorSpec(draft.factor)?.scope !== 'graph';
  const channels = channelsOf(graph);
  const allGraph = graphFactors().map((f) => f.factor_id);
  const reachable = draft.channel && factors[draft.channel]?.length ? factors[draft.channel] : allGraph;
  const scaled = draft.unit === 'fraction' || draft.unit === 'log_return';
  const scale = scaled ? 100 : 1;
  const suffix = draft.unit === 'fraction' ? ' %' : draft.unit === 'log_return' ? ' % (лог.)' : draft.unit === 'days' ? ' дн.' : '';
  const error = parameterError(draft);
  const keyLabel = factorSpec(draft.factor)?.key_label;

  const setMode = (mode: string) => {
    if (mode === 'direct') {
      const factor = directFactors()[0]?.factor_id ?? null;
      setDraft({ ...draft, channel: null, factor, key: draft.key ?? '', unit: unitOf(factor) });
    } else {
      const channel = draft.channel ?? Object.keys(channels)[0] ?? null;
      const next = channel && factors[channel]?.length ? factors[channel] : allGraph;
      setDraft({ ...draft, channel, factor: next[0] ?? null, key: null, unit: unitOf(next[0] ?? null) });
    }
  };

  return (
    <Modal opened onClose={onClose} title="Параметр сценария" size="lg" centered withCloseButton={false}>
      <Stack>
        <TextInput label={<FieldHelp label="Название" help="Короткое описание изменения для сценария и отчёта, например Падение индекса." />} value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.currentTarget.value })} />
        {structural ? (
          <Text size="sm" c="dimmed">
            Параметр не привязан к фактору: он заменяет входное значение модели (например, эластичность спроса по цене).
          </Text>
        ) : (
          <>
            <SegmentedControl
              value={direct ? 'direct' : 'graph'}
              onChange={setMode}
              data={[
                { value: 'graph', label: 'Через канал графа' },
                { value: 'direct', label: 'Напрямую по ключу' },
              ]}
            />
            {direct ? (
              <SimpleGrid cols={{ base: 1, sm: 2 }} className="portfolio-field-grid">
                <Select
                  label={<FieldHelp label="Фактор" help="Показатель рынка, изменение которого влияет на стоимость позиции. Выберите фактор, используемый её моделью." />}
                  data={directFactors().map((f) => ({ value: f.factor_id, label: f.label }))}
                  value={draft.factor}
                  allowDeselect={false}
                  onChange={(factor) => factor && setDraft({ ...draft, factor, unit: unitOf(factor) })}
                />
                <TextInput
                  label={<FieldHelp label={keyLabel || "К чему применить"} help="Обозначение должно совпадать с данными позиции: индекс, отрасль или валютная пара. Его можно найти в составе портфеля." />}
                  value={draft.key ?? ''}
                  onChange={(e) => setDraft({ ...draft, key: e.currentTarget.value })}
                />
              </SimpleGrid>
            ) : (
              <SimpleGrid cols={{ base: 1, sm: 2 }} className="portfolio-field-grid">
                <Select
                  label={<FieldHelp label="Канал графа" help="Механизм передачи события к отрасли. Шок применяется через связи этого канала." />}
                  data={Object.entries(channels).map(([value, text]) => ({ value, label: text }))}
                  value={draft.channel}
                  allowDeselect={false}
                  onChange={(channel) => {
                    const next = channel && factors[channel]?.length ? factors[channel] : allGraph;
                    const factor = draft.factor && next.includes(draft.factor) ? draft.factor : (next[0] ?? null);
                    setDraft({ ...draft, channel, factor, unit: unitOf(factor) });
                  }}
                />
                <Select
                  label={<FieldHelp label="На какой фактор действует" help="Показатель компании, который меняется через выбранный канал графа." />}
                  data={reachable.map((f) => ({ value: f, label: factorSpec(f)?.label ?? f }))}
                  value={draft.factor}
                  allowDeselect={false}
                  onChange={(factor) => factor && setDraft({ ...draft, factor, unit: unitOf(factor) })}
                />
              </SimpleGrid>
            )}
            {factorSpec(draft.factor)?.description && (
              <Text size="xs" c="dimmed">
                {factorSpec(draft.factor)!.description}
              </Text>
            )}
          </>
        )}
        <Select
          label={<FieldHelp label="Как задан" help="Точное значение для одного сценария либо распределение возможных значений для оценки интервала результатов." />}
          data={Object.entries(SCENARIO_KINDS).map(([value, text]) => ({ value, label: text }))}
          value={draft.kind}
          allowDeselect={false}
          onChange={(kind) => {
            if (!kind) return;
            const base = draft.value ?? draft.mode ?? draft.mean ?? 0;
            const next: ScenarioParameter = { ...draft, kind: kind as ScenarioKind };
            for (const [field] of FIELDS[kind as ScenarioKind]) {
              if (next[field] == null) (next as unknown as Record<string, number>)[field] = base;
            }
            setDraft(next);
          }}
        />
        <SimpleGrid cols={{ base: 1, sm: FIELDS[draft.kind].length }} className="portfolio-field-grid">
          {FIELDS[draft.kind].map(([field, caption]) => (
            <NumberInput
              key={field}
              label={<FieldHelp label={`${caption}${suffix ? `,${suffix}` : ''}`} help={draft.unit === 'log_return' ? 'Логарифмическое изменение в процентах: для падения цены на 10% укажите примерно −10,536. Для отсутствия влияния — 0.' : 'Параметр распределения в единицах, указанных в названии. Отрицательное значение означает снижение.'} />}
              decimalSeparator=","
              value={((draft[field] as number | undefined) ?? 0) * scale}
              onChange={(v) => setDraft({ ...draft, [field]: (typeof v === 'number' ? v : Number(v) || 0) / scale })}
            />
          ))}
        </SimpleGrid>
        <Text size="sm" c="dimmed">
          Сейчас: {scenarioValue(draft)}
        </Text>
        {error && (
          <Alert icon={<IconAlertTriangle />} color="orange">
            {error}
          </Alert>
        )}
        <Group justify="space-between">
          <Button variant="subtle" color="gray" leftSection={<IconTrash size={16} />} onClick={onDelete}>
            Удалить параметр
          </Button>
          <Group>
            <Button variant="default" onClick={onClose}>
              Отмена
            </Button>
            <Button
              disabled={!!error || !draft.label.trim()}
              onClick={() => onSave({ ...draft, label: draft.label.trim(), key: draft.key?.trim() || null })}
            >
              Сохранить
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
