// The credit plugin's view of a position: PD and LGD, the bond's price, liquidity, the monthly
// path, the channels' contributions, covenants with the reverse stress, risk axes; and the
// calibration note beside the money figures. Reads CalculationResult.details, which is the
// credit model's RiskResult (plugins/credit/contracts.py).
import { Alert, Box, Group, List, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react';
import { IntervalText } from '../../components/Interval';
import { TracedNumber } from '../../components/Provenance';
import { Fact, MetricsBlock, Section, SourcesBlock } from '../../components/ResultBlocks';
import { Term } from '../../components/Term';
import { compact, day, metricValue, nodeLabels, number, percent, positionPath, positionTitle } from '../../lib/format';
import { AUTHORS, label } from '../../lib/labels';
import type { Artifacts } from '../../api/types';
import type { PositionViewProps, UiPlugin } from '../sdk';
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

function Credit({ risk }: { risk: RiskDetails }) {
  const c = risk.credit;
  if (!c) return null;
  // PD before the event is the base path at the horizon end; each scenario moves it by its ΔPD.
  const basePath = risk.base?.series.risk_score?.values;
  const basePd = basePath?.[basePath.length - 1] ?? null;
  const change = risk.quantiles?.delta_pd;
  const baseLoss =
    c.expected_loss != null && c.delta_expected_loss != null ? c.expected_loss - c.delta_expected_loss : null;
  return (
    <Section
      title="Кредитный риск"
      hint={
        c.calibrated
          ? 'PD на конец горизонта — медиана и P5…P95 по сценариям; LGD и сумма под риском взяты из позиции.'
          : 'Калибровки PD нет: показан сценарный индекс риска, его нельзя читать как вероятность дефолта.'
      }
    >
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        {c.calibrated && basePd != null && change ? (
          <Fact
            name={<Term name="PD">PD после события</Term>}
            value={
              <IntervalText
                p05={basePd + change.p05}
                p50={basePd + change.p50}
                p95={basePd + change.p95}
                format={(v) => percent(v, 2)}
                align="left"
              />
            }
          />
        ) : c.calibrated ? (
          <Fact name={<Term name="PD">PD</Term>} value={percent(c.pd, 2)} />
        ) : (
          <Fact name="Индекс риска в центральном сценарии" value={number(c.risk_score, 4)} />
        )}
        {c.calibrated && basePd != null && <Fact name="PD до события" value={percent(basePd, 2)} />}
        <Fact name={<Term name="LGD">LGD</Term>} value={percent(c.lgd, 0)} />
        <Fact name={<Term name="EAD">Сумма под риском</Term>} value={metricValue(c.ead, 'RUB_million')} />
        {baseLoss != null && <Fact name="Ожидаемые потери до события" value={metricValue(baseLoss, 'RUB_million')} />}
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
    <Section title="Ликвидность" hint="Центральный сценарий, худший месяц горизонта.">
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        <Fact name="Минимальный запас денежных средств" value={metricValue(l.min_cash_headroom, 'RUB_million')} />
        <Fact name="Максимальный дефицит финансирования" value={metricValue(l.max_funding_gap, 'RUB_million')} />
        {!!l.limit_excess && <Fact name="Превышение лимита" value={metricValue(l.limit_excess, 'RUB_million')} />}
      </SimpleGrid>
    </Section>
  );
}

function Trajectories({ risk, labels }: { risk: RiskDetails; labels: Record<string, string> }) {
  const base = risk.base;
  const stress = risk.stress;
  if (!base || !stress) return null;
  const names = Object.keys(base.series).filter((n) => stress.series[n]);
  if (!names.length) return null;
  const end = base.month_ends.length - 1;
  return (
    <Section
      title="Помесячная траектория"
      hint={`Горизонт ${base.horizon} мес.; значения на ${day(base.month_ends[end])} — до события и в центральном стрессе.`}
    >
      <Table.ScrollContainer minWidth={560}>
        <Table withTableBorder fz="sm" verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Показатель</Table.Th>
              <Table.Th className="num-right">До события</Table.Th>
              <Table.Th className="num-right">
                <Term name="Стресс">Стресс</Term>
              </Table.Th>
              <Table.Th className="num-right">Изменение</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {names.map((n) => {
              const b = base.series[n].values[end];
              const s = stress.series[n].values[end];
              const unit = base.series[n].unit;
              return (
                <Table.Tr key={n}>
                  <Table.Td>{n === 'risk_score' ? 'PD / индекс риска' : (labels[n] ?? n)}</Table.Td>
                  <Table.Td className="num-right">{metricValue(b, unit)}</Table.Td>
                  <Table.Td className="num-right">{metricValue(s, unit)}</Table.Td>
                  <Table.Td className="num-right" c="dimmed">
                    {b == null || s == null ? '—' : metricValue(s - b, unit)}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Section>
  );
}

function Channels({ risk, props }: { risk: RiskDetails; props: PositionViewProps }) {
  // A channel that does not reach the position contributes nothing and is left out.
  const items = [...(risk.shapley ?? [])]
    .filter((s) => s.contribution !== 0)
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  if (!items.length) return null;
  const names = nodeLabels(props.artifacts.graph);
  const top = Math.max(...items.map((s) => Math.abs(s.contribution))) || 1;
  const inMoney = !!risk.quantiles?.delta_expected_loss;
  return (
    <Section
      title={<Term name="Вклад канала">Вклад каналов</Term>}
      hint={
        inMoney
          ? 'Значения Шепли: сумма вкладов равна росту ожидаемых потерь в центральном сценарии.'
          : 'Значения Шепли для индекса риска: PD не откалибрована, вклад в деньгах не считается.'
      }
    >
      <Stack gap={6}>
        {items.map((s) => (
          <Group key={s.channel} gap="sm" wrap="nowrap">
            <Text size="sm" w={220} lineClamp={2}>
              {names[s.channel] ?? props.shocks[s.channel] ?? s.channel}
            </Text>
            <Box style={{ flex: 1 }} h={10} bg="gray.1">
              <Box h={10} bg={s.contribution < 0 ? 'gray.5' : 'steel.5'} w={`${(Math.abs(s.contribution) / top) * 100}%`} />
            </Box>
            <Text size="sm" w={130} className="num-right">
              <TracedNumber entry={props.entries.get(positionPath(props.result.position_id, 'shapley', s.channel, 'contribution'))}>
                {inMoney ? metricValue(s.contribution, 'RUB_million') : number(s.contribution, 4)}
              </TracedNumber>
            </Text>
          </Group>
        ))}
      </Stack>
    </Section>
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
          title="Решающие показатели"
          hint="По ним срабатывают правила кредитного плагина: медиана по всем сценариям на конец горизонта, рядом — диапазон P5–P95."
        />
      )}
      <Credit risk={risk} />
      <Market risk={risk} />
      <Liquidity risk={risk} />
      <Trajectories risk={risk} labels={view.labels} />
      <Channels risk={risk} props={props} />
      <Covenants risk={risk} covenants={covenants} labels={view.labels} />
      <Reverse risk={risk} covenants={covenants} labels={view.labels} />
      <Axes risk={risk} />
      <SourcesBlock result={result} />
    </Stack>
  );
}

interface CreditNote {
  registry_id: string;
  kind: string;
  note: string;
  inclusion_rule?: { rule_id: string; text: string; approved_by: string; approved_on: string } | null;
}

/** Which calibration the money figures rest on, and which rule let reviewed positions in. */
function CalibrationNote({ artifacts }: { artifacts: Artifacts }) {
  const calibration = artifacts.notes?.credit as CreditNote | undefined;
  const slice = artifacts.portfolio?.slices['credit.loss'];
  if (!calibration || !(artifacts.results ?? []).some((r) => r.plugin_id === 'credit')) return null;
  const admitted = (slice?.flags ?? [])
    .filter((f) => f.startsWith('included_by_rule:'))
    .map((f) => f.slice('included_by_rule:'.length));
  const none = calibration.registry_id === 'none';
  return (
    <Alert
      variant="light"
      color={none ? 'orange' : 'gray'}
      icon={none ? <IconAlertTriangle /> : <IconInfoCircle />}
      title={
        none
          ? 'Калибровка PD не загружена'
          : calibration.kind === 'synthetic_demo'
            ? 'Синтетическая демо-калибровка PD'
            : `Калибровка PD ${calibration.registry_id}`
      }
    >
      <Stack gap={4}>
        <Text size="sm">
          {none
            ? 'Вероятностный выход модели — индекс риска, а не PD: денежные потери и итог кредитного среза не считаются.'
            : calibration.note}
        </Text>
        {admitted.length > 0 && calibration.inclusion_rule && (
          <Text size="sm">
            По правилу включения (утвердил: {label(AUTHORS, calibration.inclusion_rule.approved_by)},{' '}
            {day(calibration.inclusion_rule.approved_on)}) в итог кредитного среза вошли:{' '}
            {admitted.map((id) => positionTitle(id, artifacts.position_names)).join(', ')}. {calibration.inclusion_rule.text}
          </Text>
        )}
      </Stack>
    </Alert>
  );
}

const plugin: UiPlugin = {
  ...meta,
  views: { 'credit.position': CreditPosition },
  notes: CalibrationNote,
};

export default plugin;
