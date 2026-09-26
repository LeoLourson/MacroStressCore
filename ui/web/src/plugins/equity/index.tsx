// The equity plugin's view of a share: price and rate as read, the central scenario, the
// factors' contributions to the P&L (Shapley) and the distribution of losses. Reads
// CalculationResult.details, the equity model's ShareDetails (plugins/equity/schemas.py).
import { Box, Group, List, SimpleGrid, Stack, Text } from '@mantine/core';
import { Fact, HistogramBlock, MetricsBlock, Section, SourcesBlock } from '../../components/ResultBlocks';
import { Term } from '../../components/Term';
import { compact, day, metricValue, number, percent } from '../../lib/format';
import type { PositionViewProps, UiPlugin } from '../sdk';
import meta from './plugin.json';

interface ShareDetails {
  currency: string;
  base_currency: string;
  price: number;
  price_date: string;
  fx: number;
  quantity: number;
  beta_market: number;
  beta_sector: number;
  residual_sigma: number;
  dividend_per_share: number;
  value_current: number;
  central: { log_return: number; price: number; fx: number; value: number; dividends: number; pnl: number; pnl_vs_base: number };
  factor_contributions: { factor_id: string; key?: string | null; label: string; contribution: number }[];
  loss_histogram: { edges: number[]; counts: number[] };
  conventions: string[];
}

function Inputs({ d }: { d: ShareDetails }) {
  const foreign = d.currency !== d.base_currency;
  return (
    <Section title="Данные на дату оценки" hint="Цена, курс и чувствительности из снимка данных; остаточный риск — на горизонт.">
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        <Fact name={`Цена на ${day(d.price_date)}`} value={metricValue(d.price, `${d.currency}_per_unit`)} />
        {foreign && <Fact name={`Курс ${d.currency}/${d.base_currency}`} value={compact(d.fx)} />}
        <Fact name="Количество акций" value={number(d.quantity, 0)} />
        <Fact name="Бета к рынку" value={compact(d.beta_market)} />
        <Fact name="Бета к отрасли" value={compact(d.beta_sector)} />
        <Fact name="Остаточный риск на горизонте" value={percent(d.residual_sigma, 1)} />
        <Fact name="Дивиденды на акцию за горизонт" value={metricValue(d.dividend_per_share, `${d.currency}_per_unit`)} />
      </SimpleGrid>
    </Section>
  );
}

function Central({ d }: { d: ShareDetails }) {
  const money = `${d.base_currency}_million`;
  return (
    <Section
      title={<Term name="Стресс">Центральный сценарий</Term>}
      hint="При наиболее вероятных значениях шоков; остаточный риск не добавляется."
    >
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        <Fact name="Стоимость сейчас" value={metricValue(d.value_current, money)} />
        <Fact name="Стоимость на конец горизонта" value={metricValue(d.central.value, money)} />
        <Fact name="Результат с дивидендами" value={metricValue(d.central.pnl, money)} />
        <Fact name="Результат к базовому сценарию" value={metricValue(d.central.pnl_vs_base, money)} />
        <Fact name="Цена на конец горизонта" value={metricValue(d.central.price, `${d.currency}_per_unit`)} />
      </SimpleGrid>
    </Section>
  );
}

function Factors({ d }: { d: ShareDetails }) {
  const items = [...d.factor_contributions].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  if (!items.length) return null;
  const top = Math.max(...items.map((i) => Math.abs(i.contribution))) || 1;
  const money = `${d.base_currency}_million`;
  return (
    <Section
      title={<Term name="Вклад канала">Вклад факторов</Term>}
      hint="Значения Шепли в центральном сценарии: сумма вкладов равна результату. Минус — потеря, плюс — прирост."
    >
      <Stack gap={6}>
        {items.map((item) => (
          <Group key={`${item.factor_id}:${item.key}`} gap="sm" wrap="nowrap">
            <Text size="sm" w={220}>
              {item.label}
              {item.key ? ` (${item.key})` : ''}
            </Text>
            <Box style={{ flex: 1 }} h={10} bg="gray.1">
              <Box h={10} bg={item.contribution < 0 ? 'steel.6' : 'gray.5'} w={`${(Math.abs(item.contribution) / top) * 100}%`} />
            </Box>
            <Text size="sm" w={140} className="num-right">
              {item.contribution < 0 ? '▼ ' : '▲ '}
              {metricValue(item.contribution, money)}
            </Text>
          </Group>
        ))}
      </Stack>
    </Section>
  );
}

function EquityPosition({ result, view, entries }: PositionViewProps) {
  const d = result.details as unknown as ShareDetails;
  const metrics = view.blocks.find((b) => b.kind === 'metrics');
  return (
    <Stack gap="lg">
      {metrics && <MetricsBlock result={result} metricIds={metrics.metric_ids} entries={entries} title={metrics.title} />}
      <Inputs d={d} />
      <Central d={d} />
      <Factors d={d} />
      <HistogramBlock histogram={d.loss_histogram} unit={`${d.base_currency}_million`} title="Распределение потерь" />
      {d.conventions?.length > 0 && (
        <Section title="Соглашения модели">
          <List size="sm" spacing={2}>
            {d.conventions.map((line) => (
              <List.Item key={line}>{line}</List.Item>
            ))}
          </List>
        </Section>
      )}
      <SourcesBlock result={result} />
    </Stack>
  );
}

const plugin: UiPlugin = {
  ...meta,
  views: { 'equity.position': EquityPosition },
};

export default plugin;
