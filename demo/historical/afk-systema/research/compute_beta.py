"""Чувствительности акций пилота АФК и факт окна: бета к индексу, остаточная σ, доходности.

Считает по ``market-data.json`` (сырые ответы MOEX ISS — в ``raw/``):

- бета к индексу МосБиржи и остаточная σ за год до события, 24.10.2023–24.10.2024
  (``beta = cov(r, r_index) / var(r_index)``, ``r = ln(P_t / P_{t-1})``, ddof = 1);
- что случилось после события: доходность окна и вклад рынка для каждой бумаги;
- как вели себя отрасли портфеля сверх рынка: доходность отраслевых индексов МосБиржи
  за вычетом доходности широкого рынка.

    uv run --frozen python demo/historical/afk-systema/research/compute_beta.py

Пишет ``beta-computation.json``. Числа отсюда идут в снимок портфеля и в отчёт о сверке.
"""

import json
import math
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "market-data.json"
OUT = HERE / "beta-computation.json"
R = 252  # торговых дней в году — для годовой σ
#: Год до события: по нему считаются чувствительности снимка.
SENSITIVITY_WINDOW = ("2023-10-24", "2024-10-24")
EVENT, HORIZON = "2024-10-24", "2025-10-24"
#: Отраслевой индекс МосБиржи -> отрасль портфеля, за которой он наблюдает.
SECTORS = {
    "MOEXRE": "Недвижимость и строительство",
    "MOEXMM": "Сырьё, материалы и лесопромышленность",
    "MOEXTL": "Телекоммуникации",
    "MOEXCN": "Торговля",
}


def closes(ticker: str) -> dict[str, float]:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    section = payload["securities"][ticker]
    index = section["columns"].index("CLOSE")
    return {row[0]: float(row[index]) for row in section["data"] if row[index] is not None}


def aligned(series: dict[str, float], index: dict[str, float], start: str, end: str):
    days = sorted(d for d in series if d in index and start <= d <= end)
    return days


def returns(prices: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(prices, prices[1:], strict=False)]


def sensitivity(days: list[str], series: dict[str, float], index: dict[str, float]) -> dict:
    r_stock = returns([series[d] for d in days])
    r_index = returns([index[d] for d in days])
    n = len(r_stock)
    mean_s, mean_i = sum(r_stock) / n, sum(r_index) / n
    cov = sum((a - mean_s) * (b - mean_i) for a, b in zip(r_stock, r_index, strict=False)) / (n - 1)
    var_s = sum((a - mean_s) ** 2 for a in r_stock) / (n - 1)
    var_i = sum((b - mean_i) ** 2 for b in r_index) / (n - 1)
    beta = cov / var_i
    corr = cov / math.sqrt(var_s * var_i)
    residual = [a - beta * b for a, b in zip(r_stock, r_index, strict=False)]
    var_residual = sum(e * e for e in residual) / (n - 2)
    se_beta = math.sqrt(var_residual / (var_i * (n - 1)))
    return {
        "first_common_day": days[0],
        "last_common_day": days[-1],
        "prices": len(days),
        "observations": n,
        "beta_market": beta,
        "beta_95ci": [beta - 1.96 * se_beta, beta + 1.96 * se_beta],
        "t_beta": beta / se_beta,
        "corr": corr,
        "r2": corr * corr,
        "alpha_daily": mean_s - beta * mean_i,
        "alpha_annualised_pct": (mean_s - beta * mean_i) * R * 100,
        "sigma_daily_stock_pct": math.sqrt(var_s) * 100,
        "sigma_annual_stock_pct": math.sqrt(var_s) * math.sqrt(R) * 100,
        "sigma_annual_index_pct": math.sqrt(var_i) * math.sqrt(R) * 100,
        "residual_volatility": math.sqrt(var_residual) * math.sqrt(R),
    }


def window(days: list[str], series: dict[str, float], index: dict[str, float]) -> dict:
    """Что произошло в окне: доходность бумаги, рынка и разница между ними."""
    first, last = days[0], days[-1]
    stock = math.log(series[last] / series[first])
    market = math.log(index[last] / index[first])
    return {
        "first_day": first,
        "last_day": last,
        "trading_days": len(days),
        "price_start": series[first],
        "price_end": series[last],
        "log_return": stock,
        "simple_return_pct": (math.exp(stock) - 1) * 100,
        "index_log_return": market,
        "index_simple_return_pct": (math.exp(market) - 1) * 100,
        "excess_log_return": stock - market,
    }


def sector_window(days: list[str], branch: dict[str, float], index: dict[str, float]) -> dict:
    """Отрасль сверх рынка: доходность отраслевого индекса минус доходность рынка."""
    first, last = days[0], days[-1]
    sector = math.log(branch[last] / branch[first])
    market = math.log(index[last] / index[first])
    return {
        "first_day": first,
        "last_day": last,
        "trading_days": len(days),
        "index_start": branch[first],
        "index_end": branch[last],
        "log_return": sector,
        "simple_return_pct": (math.exp(sector) - 1) * 100,
        "market_log_return": market,
        "market_simple_return_pct": (math.exp(market) - 1) * 100,
        "excess_log_return": sector - market,
        "excess_fraction": math.exp(sector - market) - 1,
    }


def main():
    index = closes("MOEXBMI")
    tickers = [t for t in ("MTSS", "OZON", "SGZH", "ETLN")]
    series = {ticker: closes(ticker) for ticker in tickers}
    common = sorted(set.intersection(*[set(prices) for prices in series.values()], set(index)))
    horizon_days = [d for d in common if EVENT <= d <= HORIZON]
    sensitivities, facts = {}, {}
    for ticker in tickers:
        days = aligned(series[ticker], index, *SENSITIVITY_WINDOW)
        sensitivities[ticker] = sensitivity(days, series[ticker], index)
        facts[ticker] = window(horizon_days, series[ticker], index)
    sectors = {}
    for code, label in SECTORS.items():
        branch = closes(code)
        days = sorted(d for d in branch if d in index and EVENT <= d <= facts["MTSS"]["last_day"])
        sectors[code] = {"sector": label} | sector_window(days, branch, index)
    result = {
        "computed": date.today().isoformat(),
        "source": "MOEX ISS, режим TQBR и индекс MOEXBMI (SNDX)",
        "method": "beta = cov(r, r_index) / var(r_index); r = ln(P_t / P_t-1); "
        "ddof = 1; остаточная σ — стандартная ошибка регрессии, приведённая к году "
        "умножением на sqrt(252)",
        "sensitivity_window": list(SENSITIVITY_WINDOW),
        "event": EVENT,
        "horizon": HORIZON,
        "horizon_note": "Последний общий торговый день четырёх бумаг и индекса в окне: "
        "бумаги OZON торговались до 22.09.2025 включительно",
        "sensitivities": sensitivities,
        "facts": facts,
        "sectors": sectors,
    }
    OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"записано {OUT.relative_to(HERE.parents[3])}")
    for ticker in tickers:
        s, f = sensitivities[ticker], facts[ticker]
        low, high = s["beta_95ci"]
        print(
            f"{ticker}: beta={s['beta_market']:.3f} (95% {low:.3f}..{high:.3f}) "
            f"R2={s['r2']:.3f} resid_sigma={s['residual_volatility']:.3f} | "
            f"окно {f['first_day']}..{f['last_day']}: {f['simple_return_pct']:+.2f}% "
            f"(индекс {f['index_simple_return_pct']:+.2f}%, "
            f"сверх {f['excess_log_return'] * 100:+.2f} п.п.)"
        )
    print(f"общий торговый день конца окна: {facts['MTSS']['last_day']}")
    for code, item in sectors.items():
        print(
            f"{code} ({item['sector']}): {item['simple_return_pct']:+.2f}% "
            f"(рынок {item['market_simple_return_pct']:+.2f}%, "
            f"сверх {item['excess_log_return'] * 100:+.2f} п.п.)"
        )


if __name__ == "__main__":
    main()
