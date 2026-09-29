// The credit plugin's view of a position: PD and LGD, the bond's price, liquidity, the monthly
// path, the channels' contributions, covenants with the reverse stress, risk axes; and the
// calibration note beside the money figures. Reads CalculationResult.details, which is the
// credit model's RiskResult (plugins/credit/contracts.py).
import { Alert, Anchor, Collapse, Group, List, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react';
import { useState } from 'react';
import { ContributionsBlock, Fact, MetricsBlock, Section, SourcesBlock } from '../../components/ResultBlocks';
import { Term } from '../../components/Term';
import { change, compact, day, metricValue, nodeLabels, number, percent, positionPath, positionTitle } from '../../lib/format';
import { AUTHORS, label } from '../../lib/labels';
import { viewFor } from '../../api/catalog';
import type { Artifacts, CalculationResult } from '../../api/types';
import type { GlossContext, PositionViewProps, UiPlugin } from '../sdk';
import meta from './plugin.json';

interface Quantiles {
  p05: number;
  p50: number;
  p95: number;
  es95?: number | null;
  unit: string;
}

interface Series {
  unit: string;
  values: (number | null)[];
}

interface Trajectory {
  horizon: number;
  month_ends: string[];
  series: Record<string, Series>;
}

interface CovenantResult {
  covenant_id: string;
  metric: string;
  breach_probability: number;
  min_headroom: number;
  breach_date?: string | null;
}

interface ReverseStress {
  target: string;
  status: 'found' | 'already_breached' | 'not_breached' | string;
  lambda_star?: number | null;
}

interface Axis {
  axis: string;
  band: 'not_assessed' | 'low' | 'medium' | 'high' | 'critical';
  reason?: string;
}

interface RiskDetails {
  base?: Trajectory | null;
  stress?: Trajectory | null;
  credit?: {
    calibrated: boolean;
    segment_id: string;
    risk_score?: number | null;
    pd?: number | null;
    lgd?: number | null;
    ead?: number | null;
    expected_loss?: number | null;
    delta_expected_loss?: number | null;
  } | null;
  market?: {
    base_price?: number | null;
    stress_price?: number | null;
    price_change?: number | null;
    duration?: number | null;
    convexity?: number | null;
  } | null;
  liquidity?: { min_cash_headroom: number; max_funding_gap: number; limit_excess?: number } | null;
  covenants?: CovenantResult[];
  quantiles?: Record<string, Quantiles>;
  shapley?: { channel: string; contribution: number }[];
  reverse_stress?: ReverseStress[];
  axes?: Axis[];
}

interface Covenant {
  covenant_id: string;
  metric: string;
  operator: 'ge' | 'le';
  threshold: number;
  unit: string;
}

const SEGMENTS: Record<string, string> = {
  corporate: 'корпоративные заёмщики',
  project_finance: 'проектное финансирование',
  leasing: 'лизинговые компании',
};

const AXES: Record<string, string> = {
  credit: 'Кредитный риск',
  market: 'Рыночный риск',
  liquidity: 'Ликвидность',
  covenant: 'Ковенанты',
  data_and_model: 'Данные и модель',
};

// Impact level carried by words, weight and a mark; colour only repeats it.
const BANDS: Record<Axis['band'], { text: string; weight: number; mark: string }> = {
  not_assessed: { text: 'не оценено: правила оценки не утверждены', weight: 400, mark: '—' },
  low: { text: 'низкий', weight: 400, mark: '○' },
  medium: { text: 'средний', weight: 500, mark: '◐' },
  high: { text: 'высокий', weight: 700, mark: '●' },
  critical: { text: 'критический', weight: 800, mark: '▲' },
};

function covenantText(id: string, covenants: Covenant[], labels: Record<string, string>): string {
  const covenant = covenants.find((c) => c.covenant_id === id);
  if (!covenant) return id;
  const sign = covenant.operator === 'ge' ? '≥' : '≤';
  return `${labels[`covenant:${covenant.metric}`] ?? labels[covenant.metric] ?? covenant.metric} ${sign} ${metricValue(covenant.threshold, covenant.unit)}`;
}

/**
 * The level before the event of what a credit change metric measures: the expected loss for
 * its growth, PD (or the risk index) at the horizon end of the base path for theirs.
 */
function baseline(result: CalculationResult, metricId: string): number | null {
  const risk = result.details as RiskDetails;
  if (metricId === 'credit.delta_expected_loss') {
    const c = risk.credit;
    return c?.expected_loss != null && c.delta_expected_loss != null ? c.expected_loss - c.delta_expected_loss : null;
  }
  if (metricId === 'credit.delta_pd' || metricId === 'credit.delta_risk_score') {
    const path = risk.base?.series.risk_score?.values;
    return path?.[path.length - 1] ?? null;
  }
  return null;
}

function Credit({ risk, result }: { risk: RiskDetails; result: CalculationResult }) {
  const c = risk.credit;
  if (!c) return null;
  // PD before and after the event is the row of its growth above, when the base path gives it.
  const pdShown =
    c.calibrated && !!result.metrics['credit.delta_pd']?.quantiles && baseline(result, 'credit.delta_pd') != null;
  return (
    <Section
      title="Кредитный риск"
      hint={
        c.calibrated
          ? `LGD и сумма под риском взяты из позиции.${pdShown ? ' PD до и после события — в ключевых показателях выше.' : ''}`
          : 'Калибровки PD нет: показан сценарный индекс риска, его нельзя читать как вероятность дефолта.'
      }
    >
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        {!c.calibrated ? (
          <Fact name="Индекс риска в центральном сценарии" value={number(c.risk_score, 4)} />
        ) : (
          !pdShown && <Fact name={<Term name="PD">PD</Term>} value={percent(c.pd, 2)} />
        )}
        <Fact name={<Term name="LGD">LGD</Term>} value={percent(c.lgd, 0)} />
        <Fact name={<Term name="EAD">Сумма под риском</Term>} value={metricValue(c.ead, 'RUB_million')} />
        <Fact name="Модель PD" value={label(SEGMENTS, c.segment_id)} />
      </SimpleGrid>
    </Section>
  );
}

function Market({ risk }: { risk: RiskDetails }) {
  const m = risk.market;
  if (!m || m.base_price == null) return null;
  return (
    <Section title="Облигация" hint="Полная переоценка на кривой; цена на 100 номинала.">
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        <Fact name="Цена до события" value={number(m.base_price)} />
        <Fact name="Цена в стрессе" value={number(m.stress_price)} />
        <Fact name="Изменение цены" value={number(m.price_change)} />
        <Fact name="Спред-дюрация" value={number(m.duration)} />
        <Fact name="Выпуклость" value={number(m.convexity)} />
      </SimpleGrid>
    </Section>
  );
}

function Liquidity({ risk }: { risk: RiskDetails }) {
  const l = risk.liquidity;
  if (!l) return null;
  return (
    <Section
      title="Ликвидность в центральном сценарии"
      hint="Худший месяц горизонта при наиболее вероятных значениях шоков. Дефицит на конец горизонта по всем сценариям — в показателях выше."
    >
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        <Fact name="Минимальный запас денежных средств" value={metricValue(l.min_cash_headroom, 'RUB_million')} />
        <Fact name="Максимальный дефицит финансирования" value={metricValue(l.max_funding_gap, 'RUB_million')} />
        {!!l.limit_excess && <Fact name="Превышение лимита" value={metricValue(l.limit_excess, 'RUB_million')} />}
      </SimpleGrid>
    </Section>
  );
}

function Trajectories({ risk, labels }: { risk: RiskDetails; labels: Record<string, string> }) {
  const [all, setAll] = useState(false);
  const base = risk.base;
  const stress = risk.stress;
  if (!base || !stress) return null;
  // In the order the plugin declares its series (revenue, costs, debt, liquidity, ratios);
  // the stored details keep no order of their own.
  const declared = Object.keys(labels);
  const rank = (n: string) => (n === 'risk_score' ? -1 : declared.includes(n) ? declared.indexOf(n) : declared.length);
  const end = base.month_ends.length - 1;
  const rows = Object.keys(base.series)
    .filter((n) => stress.series[n])
    .sort((a, b) => rank(a) - rank(b))
    .map((n) => {
      const unit = base.series[n].unit;
      const b = base.series[n].values[end];
      const s = stress.series[n].values[end];
      return { n, unit, b, s, moved: metricValue(b, unit) !== metricValue(s, unit) };
    });
  if (!rows.length) return null;
  const still = rows.filter((r) => !r.moved).length;
  const shown = all ? rows : rows.filter((r) => r.moved);
  return (
    <Section
      title="Показатели компании на конец горизонта"
      hint={`На ${day(base.month_ends[end])}: до события и в центральном сценарии — одна траектория при наиболее вероятных значениях шоков. Медианы и диапазоны по всем сценариям — в показателях выше.`}
    >
      <Table.ScrollContainer minWidth={560}>
        <Table withTableBorder fz="sm" verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Показатель</Table.Th>
              <Table.Th className="num-right">До события</Table.Th>
              <Table.Th className="num-right">
                <Term name="Стресс">Центральный сценарий</Term>
              </Table.Th>
              <Table.Th className="num-right">Изменение</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shown.map(({ n, unit, b, s }) => (
              <Table.Tr key={n}>
                <Table.Td>{n === 'risk_score' ? 'PD / индекс риска' : (labels[n] ?? n)}</Table.Td>
                <Table.Td className="num-right">{metricValue(b, unit)}</Table.Td>
                <Table.Td className="num-right">{metricValue(s, unit)}</Table.Td>
                <Table.Td className="num-right" c="dimmed">
                  {b == null || s == null ? '—' : change(s - b, unit)}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {still > 0 && (
        <Anchor component="button" size="xs" w="fit-content" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? 'Скрыть показатели без изменений' : `Показать без изменений: ${still}`}
        </Anchor>
      )}
    </Section>
  );
}

function Channels({ risk, props }: { risk: RiskDetails; props: PositionViewProps }) {
  const names = nodeLabels(props.artifacts.graph);
  const inMoney = !!risk.quantiles?.delta_expected_loss;
  return (
    <ContributionsBlock
      items={(risk.shapley ?? []).map((s) => ({
        key: s.channel,
        label: names[s.channel] ?? props.shocks[s.channel] ?? s.channel,
        value: s.contribution,
      }))}
      metricId={inMoney ? 'credit.delta_expected_loss' : 'credit.delta_risk_score'}
      format={(v) => (inMoney ? metricValue(v, 'RUB_million') : number(v, 4))}
      title={<Term name="Вклад канала">Вклад каналов</Term>}
      hint={
        inMoney
          ? 'Значения Шепли в центральном сценарии: сумма вкладов равна росту ожидаемых потерь в нём.'
          : 'Значения Шепли для индекса риска: PD не откалибрована, вклад в деньгах не считается.'
      }
      origin={(channel) => props.entries.get(positionPath(props.result.position_id, 'shapley', channel, 'contribution'))}
    />
  );
}

function Covenants({ risk, covenants, labels }: { risk: RiskDetails; covenants: Covenant[]; labels: Record<string, string> }) {
  const items = risk.covenants ?? [];
  if (!items.length) return null;
  return (
    <Section
      title={<Term name="Ковенант">Ковенанты</Term>}
      hint="Вероятность — доля сценариев с нарушением хотя бы в одну дату проверки. Запас меньше нуля — порог пробит в центральном сценарии."
    >
      <Table.ScrollContainer minWidth={620}>
        <Table withTableBorder fz="sm" verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Ковенант</Table.Th>
              <Table.Th className="num-right">Вероятность нарушения</Table.Th>
              <Table.Th className="num-right">Минимальный запас</Table.Th>
              <Table.Th>Худший месяц</Table.Th>
              <Table.Th>Итог</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((c) => {
              const broken = c.breach_probability >= 0.5;
              return (
                <Table.Tr key={c.covenant_id}>
                  <Table.Td>{covenantText(c.covenant_id, covenants, labels)}</Table.Td>
                  <Table.Td className="num-right">{percent(c.breach_probability, 0)}</Table.Td>
                  <Table.Td className="num-right">{number(c.min_headroom)}</Table.Td>
                  <Table.Td>{c.breach_date ? day(c.breach_date) : '—'}</Table.Td>
                  <Table.Td fw={broken ? 700 : 400}>{broken ? '✕ под угрозой' : '✓ соблюдается'}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Section>
  );
}

function reverseText(item: ReverseStress): string {
  switch (item.status) {
    case 'found': {
      const share = item.lambda_star ?? 0;
      return share <= 1
        ? `нарушится уже при ${percent(share, 0)} силы события`
        : `выдержит событие; нарушится при силе ×${compact(Math.round(share * 100) / 100)}`;
    }
    case 'already_breached':
      return 'нарушен ещё до события';
    case 'not_breached':
      return 'не нарушится даже при кратном усилении шока';
    default:
      return item.status;
  }
}

function Reverse({ risk, covenants, labels }: { risk: RiskDetails; covenants: Covenant[]; labels: Record<string, string> }) {
  const items = risk.reverse_stress ?? [];
  if (!items.length) return null;
  return (
    <Section
      title={<Term name="Обратный стресс-тест">Обратный стресс-тест</Term>}
      hint="Какая доля силы события доводит ковенант до нарушения. Меньше 100 % — запаса прочности нет."
    >
      <List size="sm" spacing={4}>
        {items.map((item) => (
          <List.Item key={item.target}>
            <b>{covenantText(item.target, covenants, labels)}</b>: {reverseText(item)}
          </List.Item>
        ))}
      </List>
    </Section>
  );
}

function Axes({ risk }: { risk: RiskDetails }) {
  // Without approved banding rules every axis is not assessed: there is nothing to show.
  if (!(risk.axes ?? []).some((axis) => axis.band !== 'not_assessed')) return null;
  return (
    <Section title="Оценка по осям риска">
      <Table withTableBorder fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Ось риска</Table.Th>
            <Table.Th>Уровень</Table.Th>
            <Table.Th>Основание</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {risk.axes!.map((axis) => {
            const band = BANDS[axis.band] ?? BANDS.not_assessed;
            return (
              <Table.Tr key={axis.axis}>
                <Table.Td>{label(AXES, axis.axis)}</Table.Td>
                <Table.Td>
                  <Text size="sm" fw={band.weight} span>
                    {band.mark} {band.text}
                  </Text>
                </Table.Td>
                <Table.Td>{axis.reason || '—'}</Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Section>
  );
}

function CreditPosition(props: PositionViewProps) {
  const { result, context, view, entries } = props;
  const levels = (metricId: string) => baseline(result, metricId);
  const risk = result.details as RiskDetails;
  const covenants = ((context?.instrument.terms.covenants ?? []) as Covenant[]).filter((c) => c.covenant_id);
  const metrics = view.blocks.find((b) => b.kind === 'metrics');
  return (
    <Stack gap="lg">
      {metrics && (
        <MetricsBlock
          result={result}
          metricIds={metrics.metric_ids}
          entries={entries}
          title="Другие показатели на конец горизонта"
          hint="Медиана по всем сценариям и диапазон P5–P95. По ним и по ключевым показателям срабатывают правила рекомендаций."
          baseline={levels}
          exclude={view.summary_metrics}
        />
      )}
      <Credit risk={risk} result={result} />
      <Market risk={risk} />
      <Liquidity risk={risk} />
      <Trajectories risk={risk} labels={view.labels} />
      <Channels risk={risk} props={props} />
      <Covenants risk={risk} covenants={covenants} labels={view.labels} />
      <Reverse risk={risk} covenants={covenants} labels={view.labels} />
      <Axes risk={risk} />
      <SourcesBlock result={result} context={context} />
    </Stack>
  );
}

interface CreditNote {
  registry_id: string;
  kind: string;
  note: string;
  inclusion_rule?: { rule_id: string; text: string; approved_by: string; approved_on: string } | null;
}

/**
 * Which calibration the money figures rest on, and which rule let reviewed positions in. A
 * missing calibration is a problem and stands out; a calibration in force is one line.
 */
function CalibrationNote({ artifacts }: { artifacts: Artifacts }) {
  const [open, setOpen] = useState(false);
  const calibration = artifacts.notes?.credit as CreditNote | undefined;
  const slice = artifacts.portfolio?.slices['credit.loss'];
  if (!calibration || !(artifacts.results ?? []).some((r) => r.plugin_id === 'credit')) return null;
  const admitted = (slice?.flags ?? [])
    .filter((f) => f.startsWith('included_by_rule:'))
    .map((f) => f.slice('included_by_rule:'.length));
  if (calibration.registry_id === 'none') {
    return (
      <Alert variant="light" color="orange" icon={<IconAlertTriangle />} title="Калибровка PD не загружена">
        <Text size="sm">
          Вероятностный выход модели — индекс риска, а не PD: денежные потери и итог кредитного среза не считаются.
        </Text>
      </Alert>
    );
  }
  return (
    <Stack gap={4}>
      <Group gap={6} wrap="nowrap" align="flex-start" c="dark.3">
        <IconInfoCircle size={14} style={{ flexShrink: 0, marginTop: 2 }} />
        <Text size="xs">
          {calibration.kind === 'synthetic_demo'
            ? 'PD рассчитана по синтетической демо-калибровке: только для демонстрации, не для кредитных решений.'
            : `PD рассчитана по калибровке ${calibration.registry_id}.`}{' '}
          <Anchor component="button" size="xs" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
            {open ? 'Свернуть' : 'Подробнее'}
          </Anchor>
        </Text>
      </Group>
      <Collapse in={open}>
        <Stack gap={4} pl={20} maw="90ch">
          <Text size="xs" c="dark.3">
            {calibration.note}
          </Text>
          {admitted.length > 0 && calibration.inclusion_rule && (
            <Text size="xs" c="dark.3">
              По правилу включения (утвердил: {label(AUTHORS, calibration.inclusion_rule.approved_by)},{' '}
              {day(calibration.inclusion_rule.approved_on)}) в итог кредитного среза вошли:{' '}
              {admitted.map((id) => positionTitle(id, artifacts.position_names)).join(', ')}. {calibration.inclusion_rule.text}
            </Text>
          )}
        </Stack>
      </Collapse>
    </Stack>
  );
}

/** Covenants are terms of a credit instrument; their metric names come from its view. */
function* covenantGlosses({ artifacts }: GlossContext): Iterable<[string, string]> {
  for (const context of artifacts.positions ?? []) {
    const labels = viewFor(context.instrument.instrument_type)?.labels ?? {};
    const covenants = (context.instrument.terms.covenants ?? []) as {
      covenant_id?: string;
      metric: string;
      operator: string;
      threshold: number;
      unit: string;
    }[];
    for (const c of covenants) {
      if (!c.covenant_id) continue;
      const sign = c.operator === 'ge' ? '≥' : '≤';
      yield [c.covenant_id, `${labels[`covenant:${c.metric}`] ?? labels[c.metric] ?? c.metric} ${sign} ${metricValue(c.threshold, c.unit)}`];
    }
  }
}

const GLOSSARY: Record<string, string> = {
  'ΔEL': 'Рост ожидаемых потерь: насколько вырастут потери по позиции из-за события.',
  'ΔPD': 'Рост вероятности дефолта заёмщика из-за события.',
  PD: 'Вероятность дефолта заёмщика на горизонте расчёта.',
  LGD: 'Доля суммы, которая будет потеряна при дефолте.',
  EAD: 'Сумма под риском: сколько банк может потерять по позиции.',
  ICR: 'Покрытие процентов: во сколько раз EBITDA больше процентных платежей.',
  'Ковенант': 'Условие кредитного договора, например «Долг / EBITDA не выше 3».',
  'Обратный стресс-тест': 'Какая сила события доводит ковенант до нарушения.',
};

const plugin: UiPlugin = {
  ...meta,
  views: { 'credit.position': CreditPosition },
  notes: CalibrationNote,
  glosses: covenantGlosses,
  baseline,
  glossary: GLOSSARY,
};

export default plugin;
