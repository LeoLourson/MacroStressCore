// The equity plugin's view of a share: price and rate as read, the factors' contributions to
// the P&L in the central scenario (Shapley) and the distribution of losses. Reads
// CalculationResult.details, the equity model's ShareDetails (plugins/equity/schemas.py).
import { List, SimpleGrid, Stack } from '@mantine/core';
import { ContributionsBlock, Fact, HistogramBlock, MetricsBlock, Section, SourcesBlock } from '../../components/ResultBlocks';
import { MathText } from '../../components/MathText';
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

/**
 * The factors' parts of the result in the central scenario. Its total is one path, not the
 * median over the scenarios: both are named, so the two close numbers are not taken for one.
 */
function Factors({ d, median }: { d: ShareDetails; median: number | null | undefined }) {
  const money = `${d.base_currency}_million`;
  return (
    <ContributionsBlock
      items={d.factor_contributions.map((item) => ({
        key: `${item.factor_id}:${item.key ?? ''}`,
        label: item.key ? `${item.label} (${item.key})` : item.label,
        value: item.contribution,
      }))}
      metricId="equity.pnl_vs_base"
      format={(v) => metricValue(v, money)}
      title={<Term name="Вклад канала">Вклад факторов</Term>}
      hint={
        `Значения Шепли в центральном сценарии — при наиболее вероятных значениях шоков, без остаточного риска. ` +
        `Сумма вкладов — результат к базовому сценарию в нём: ${metricValue(d.central.pnl_vs_base, money)}` +
        (median != null ? `; медиана по всем сценариям — ${metricValue(median, money)}.` : '.')
      }
    />
  );
}

function EquityPosition({ result, view, entries }: PositionViewProps) {
  const d = result.details as unknown as ShareDetails;
  const metrics = view.blocks.find((b) => b.kind === 'metrics');
  return (
    <Stack gap="lg">
      {metrics && (
        <MetricsBlock
          result={result}
          metricIds={metrics.metric_ids}
          entries={entries}
          title="Другие показатели на конец горизонта"
          exclude={view.summary_metrics}
        />
      )}
      <Inputs d={d} />
      <Factors d={d} median={result.metrics['equity.pnl_vs_base']?.quantiles?.p50} />
      <HistogramBlock
        histogram={d.loss_histogram}
        unit={`${d.base_currency}_million`}
        title="Распределение потерь"
        quantiles={result.metrics['equity.loss']?.quantiles}
      />
      {d.conventions?.length > 0 && (
        <Section title="Соглашения модели">
          <List size="sm" spacing={4}>
            {d.conventions.map((line) => (
              <List.Item key={line}>
                <MathText>{line}</MathText>
              </List.Item>
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
