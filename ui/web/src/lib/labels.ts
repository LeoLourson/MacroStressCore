// Russian names for API identifiers. Everything a plugin declares — instrument types, flags,
// actions, rules, sources of the demo data — comes from the server's catalog: api/catalog.ts
// fills the tables below when the app starts. Only the platform's own words live here.

export const ROLES: Record<string, string> = {
  analyst: 'Аналитик',
  risk_manager: 'Риск-менеджер',
  admin: 'Администратор',
  demo: 'Демо-доступ',
};

export const MODES: Record<string, string> = {
  production: 'Рабочий контур',
  demo: 'Демо-контур',
};

/** Filled from the catalog: instrument type id -> its name. */
export const INSTRUMENT_TYPES: Record<string, string> = {};

/** Filled from the catalog: recommended action id -> what to do. */
export const ACTIONS: Record<string, string> = {};

/** Filled from the catalog: rule id -> why it fired. */
export const RULES: Record<string, string> = {};

/** Filled from the catalog: flag code (or «prefix:» with {}) -> words, as the server words it. */
export const FLAG_TABLE: Record<string, string> = {};

/** Filled from the catalog: where the numbers of the demo data come from, and who stands behind them. */
export const SOURCES: Record<string, string> = {};
export const AUTHORS: Record<string, string> = { 'demo:auto': 'автоматически (демо-режим)' };

export const NODE_KINDS: Record<string, string> = {
  event: 'Событие',
  channel: 'Каналы влияния',
  sector: 'Отрасли',
  factor: 'Факторы',
};

export const EVIDENCE_KINDS: Record<string, string> = {
  document: 'Фрагмент текста события',
  historical_estimate: 'Историческая оценка',
  expert_assumption: 'Допущение эксперта',
};

export const PASSPORT: Record<string, string> = {
  event_type: 'Тип события',
  authority: 'Орган',
  act_reference: 'Акт',
  effective_date: 'Вступает в силу',
  territory: 'Территория',
};

export const SCENARIO_KINDS: Record<string, string> = {
  point: 'Одно значение',
  triangular: 'Диапазон с наиболее вероятным значением',
  uniform: 'Равновероятный диапазон',
  truncated_normal: 'Около среднего, с границами',
};

export const DISTRIBUTIONS: Record<string, string> = {
  point: 'Точное значение',
  triangular: 'Диапазон с наиболее вероятным значением',
  uniform: 'Равновероятный диапазон',
  lognormal: 'Логнормальное распределение',
};

export const RULE_CHECKS: Record<string, string> = {
  V1: 'не соответствует формату',
  V2: 'неизвестный фактор или единица',
  V7: 'в графе есть цикл',
  V8: 'у связи нет источника',
};

export const RESULT_STATUS: Record<string, string> = {
  ok: 'рассчитано',
  uncalibrated: 'модель не откалибрована',
  needs_review: 'нужна ручная проверка',
  incomplete: 'неполный расчёт',
  invalid: 'расчёт недействителен',
};

export const EXECUTION: Record<string, string> = {
  completed: 'рассчитана',
  not_run: 'не рассчитана',
  failed: 'расчёт завершился ошибкой',
};

export const DATA_QUALITY: Record<string, string> = {
  high: 'высокое',
  medium: 'среднее',
  low: 'низкое',
  unknown: 'не оценено',
};

/** Coverage bases of the slices; a plugin's slice names its own in the catalog. */
export const EXPOSURE_BASES: Record<string, string> = {
  ead: 'суммы под риском',
  market_value: 'стоимости позиций',
};

export const PROVIDERS: Record<string, string> = {
  local: 'Локальная LLM',
  deepseek: 'DeepSeek API',
  mock: 'Заглушка без LLM',
};

// Known stop reasons of a run, by a fragment of the technical message.
export const REASONS: Record<string, string> = {
  'Document is unparsed': 'Из документа не удалось извлечь текст: загрузите текстовую версию.',
  'No affected portfolio OKVED': 'Событие не затрагивает отрасли портфеля.',
  'No event-to-factor path': 'В графе нет пути от события к факторам позиций портфеля.',
  'LLM request failed': 'Языковая модель не ответила: повторите запуск позже.',
  'Missing, duplicate or unexpected position branches': 'Расчёт по части позиций не завершился.',
  "did not use the run's shared macro matrix": 'Позиции посчитаны на разных сценариях.',
  'plugin versions changed': 'Код плагинов изменился после запуска: запустите стресс-тест заново.',
  'Run failed; consult the server log': 'Внутренняя ошибка сервиса: обратитесь к администратору.',
};

// Terms a risk manager meets on screen, explained in one sentence each.
export const GLOSSARY: Record<string, string> = {
  'ΔEL': 'Рост ожидаемых потерь: насколько вырастут потери по позиции из-за события.',
  'ΔPD': 'Рост вероятности дефолта заёмщика из-за события.',
  PD: 'Вероятность дефолта заёмщика на горизонте расчёта.',
  LGD: 'Доля суммы, которая будет потеряна при дефолте.',
  EAD: 'Сумма под риском: сколько банк может потерять по позиции.',
  ICR: 'Покрытие процентов: во сколько раз EBITDA больше процентных платежей.',
  'P5–P95':
    'Диапазон, в который результат попадает в 90 % сценариев. P50 — медиана: половина сценариев лучше, половина хуже.',
  ES95: 'Средние потери в худших 5 % сценариев.',
  'Монте-Карло':
    'Расчёт на тысячах случайных сценариев силы события; из них получается диапазон результата.',
  'Вклад канала':
    'Какая часть результата приходится на каждый канал или фактор (значения Шепли); сумма вкладов равна полному изменению.',
  'Эластичность':
    'Сила связи: на сколько процентов меняется следствие при изменении причины на 1 %.',
  'Обратный стресс-тест': 'Какая сила события доводит ковенант до нарушения.',
  'Стресс': 'Значение при центральных (наиболее вероятных) значениях шоков события.',
  'Ковенант': 'Условие кредитного договора, например «Долг / EBITDA не выше 3».',
  'Срез портфеля':
    'Итог по одной мере с одним смыслом: кредитные потери и рыночный результат считаются отдельно и не складываются.',
};

export function label(mapping: Record<string, string>, key: string | null | undefined): string {
  if (key == null) return '—';
  return mapping[key] ?? key;
}

export function reasonText(message: string): string | null {
  for (const [part, text] of Object.entries(REASONS)) {
    if (message.includes(part)) return text;
  }
  return null;
}

const DIGITS = /\d/;

/**
 * A flag in words, worded as the server words it (reporting/wording.py): an exact entry,
 * else «prefix:>» for a flag carried inside another, else «prefix:» with its argument.
 * `shocks` names the run's scenario parameters by the analyst's labels.
 */
export function flagOne(flag: string, shocks?: Record<string, string>): string {
  if (flag in FLAG_TABLE) return FLAG_TABLE[flag];
  const at = flag.indexOf(':');
  const prefix = at < 0 ? flag : flag.slice(0, at);
  const rest = at < 0 ? '' : flag.slice(at + 1).trim();
  if (`${prefix}:>` in FLAG_TABLE) return flagOne(rest, shocks);
  const phrase = FLAG_TABLE[`${prefix}:`];
  if (phrase !== undefined) {
    if (!phrase.includes('{}')) return phrase;
    const argument = shocks?.[rest] ?? rest;
    if (DIGITS.test(argument)) return phrase.replace('«{}»', '').replace('{}', '').replace(/\s+/g, ' ').trim();
    return phrase.replace('{}', argument);
  }
  if (/^V\d+$/.test(prefix)) return `не пройдена проверка ${prefix}${rest ? ` (${rest})` : ''}`;
  return flag;
}

/** Machine flags inside a sentence from the server, replaced by their Russian names. */
export function translateFlags(text: string): string {
  return text
    .split('; ')
    .map((part) => {
      // A whole flag may carry free text after its prefix; otherwise flags sit inside words.
      const whole = flagOne(part.trim());
      return whole !== part.trim()
        ? whole
        : part.replace(/[a-z][a-z0-9_]*(?::[a-z0-9_./-]+)?/g, (token) => flagOne(token));
    })
    .join('; ');
}

export function flagList(flags: string[] | null | undefined, shocks?: Record<string, string>): string[] {
  return [...new Set((flags ?? []).map((flag) => flagOne(flag, shocks)))];
}

/** Scenario parameter name -> the label the analyst confirmed. */
export function shockLabels(parameters: Record<string, { label?: string }> | null | undefined): Record<string, string> {
  return Object.fromEntries(
    Object.entries(parameters ?? {}).flatMap(([name, p]) => (p.label ? [[name, p.label]] : [])),
  );
}

export function flagText(flags: string[] | null | undefined): string {
  return flagList(flags).join(', ');
}
