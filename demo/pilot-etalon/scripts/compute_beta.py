# Исследовательский скрипт пилота «Эталон». Каталог собирается не из него: build_pilot_afk.py
# читает demo/pilot-afk/beta-computation.json, который пишет demo/pilot-afk/compute_beta.py.
# Отличия от версии АФК (по факту кода): одна бумага ETLN против MOEXBMI вместо MTSS/OZON/SGZH/ETLN;
# окна 2023-07-01..2024-06-30 и календарный 2023 вместо года до 24.10.2024; данные из
# etln-quotes-2023-01_2024-12.json и moex-index-2023-01_2024-12.json в demo/pilot-etalon/
# вместо market-data.json; дополнительно пишет se_alpha, моменты и σ индекса, но не считает
# доходность окна после события, отраслевые индексы и остаточную σ; отказывается перезаписать
# beta-computation.json без --force; формула беты та же (лог-доходности, ddof = 1).
"""Beta of ETLN against MOEXBMI on daily returns, plus the audit trail for the report.

Windows:
  main : 2023-07-01 .. 2024-06-30   (pilot window around both stress dates)
  extra: 2023-01-01 .. 2023-12-31   (calendar 2023)

beta = cov(r_ETLN, r_index) / var(r_index), sample moments (ddof = 1),
r = ln(P_t / P_{t-1}) on trading days where both instruments traded.
"""

import json
import math
import os
import statistics
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
R = 252  # trading days per year, for the annualised standard error


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload


def closes(payload, close_index):
    """date -> close, keeping only rows with a usable close."""
    out = {}
    for row in payload["data"]:
        value = row[close_index]
        if value is None:
            continue
        out[row[0]] = float(value)
    return out


def pairs(etln, index, start, end):
    """Aligned (date, p_etln, p_index) on common trading days inside [start, end]."""
    days = sorted(d for d in etln if d in index and start <= d <= end)
    return days, [(d, etln[d], index[d]) for d in days]


def returns(series):
    """(dates, log returns) from a list of (date, price) pairs."""
    dates, values = [], []
    for (prev, cur) in zip(series, series[1:]):
        dates.append(cur[0])
        values.append(math.log(cur[1] / prev[1]))
    return dates, values


def analyse(etln, index, start, end):
    days, joined = pairs(etln, index, start, end)
    r_days, r_etln = returns([(d, e) for d, e, _ in joined])
    _, r_index = returns([(d, i) for d, _, i in joined])
    assert len(r_etln) == len(r_index)

    mean_e = statistics.fmean(r_etln)
    mean_i = statistics.fmean(r_index)
    cov = sum((a - mean_e) * (b - mean_i) for a, b in zip(r_etln, r_index)) / (len(r_etln) - 1)
    var_e = sum((a - mean_e) ** 2 for a in r_etln) / (len(r_etln) - 1)
    var_i = sum((b - mean_i) ** 2 for b in r_index) / (len(r_index) - 1)
    beta = cov / var_i
    corr = cov / math.sqrt(var_e * var_i)
    resid = [a - beta * b for a, b in zip(r_etln, r_index)]
    sse = sum(e * e for e in resid)
    var_resid = sse / (len(r_etln) - 2)
    se_beta = math.sqrt(var_resid / (var_i * (len(r_etln) - 1)))
    se_alpha = math.sqrt(var_resid * (1 / len(r_etln) + mean_i ** 2 / (var_i * (len(r_etln) - 1))))
    alpha = mean_e - beta * mean_i

    return {
        "start": start,
        "end": end,
        "first_common_day": days[0],
        "last_common_day": days[-1],
        "prices": len(days),
        "observations": len(r_etln),
        "mean_r_etln": mean_e,
        "mean_r_index": mean_i,
        "cov": cov,
        "var_etln": var_e,
        "var_index": var_i,
        "beta": beta,
        "corr": corr,
        "r2": corr * corr,
        "alpha_daily": alpha,
        "alpha_annualised_pct": alpha * R * 100,
        "se_beta": se_beta,
        "se_alpha_daily": se_alpha,
        "t_beta": beta / se_beta,
        "beta_95ci": [beta - 1.96 * se_beta, beta + 1.96 * se_beta],
        "sigma_daily_etln_pct": math.sqrt(var_e) * 100,
        "sigma_daily_index_pct": math.sqrt(var_i) * 100,
        "sigma_annual_etln_pct": math.sqrt(var_e) * math.sqrt(R) * 100,
        "sigma_annual_index_pct": math.sqrt(var_i) * math.sqrt(R) * 100,
    }


def main():
    quotes = load("etln-quotes-2023-01_2024-12.json")
    index = load("moex-index-2023-01_2024-12.json")
    etln = closes(quotes, quotes["columns"].index("CLOSE"))
    bmi = closes(index, index["columns"].index("CLOSE"))

    windows = [("main", "2023-07-01", "2024-06-30"), ("calendar_2023", "2023-01-01", "2023-12-31")]
    results = {}
    for label, start, end in windows:
        res = analyse(etln, bmi, start, end)
        results[label] = res
        print(f"\n=== {label}: {start} .. {end} ===")
        for key in ("first_common_day", "last_common_day", "prices", "observations",
                    "mean_r_etln", "mean_r_index", "var_index", "cov", "beta", "corr", "r2",
                    "alpha_daily", "alpha_annualised_pct", "se_beta", "se_alpha_daily", "t_beta",
                    "beta_95ci", "sigma_daily_etln_pct", "sigma_daily_index_pct",
                    "sigma_annual_etln_pct", "sigma_annual_index_pct"):
            print(f"  {key} = {res[key]}")

    out = {
        "computed": date.today().isoformat(),
        "method": "beta = cov(r_ETLN, r_index) / var(r_index); r = ln(P_t/P_t-1); sample moments (ddof=1)",
        "etln_source": quotes["source"] + " / " + quotes["security"] + " / " + quotes["board"],
        "index_source": index["source"] + " / " + index["security"] + " / " + index["board"],
        "results": results,
    }
    path = os.path.join(DATA, "beta-computation.json")
    if os.path.exists(path) and "--force" not in sys.argv:
        raise SystemExit(f"refusing to overwrite {path}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=4)
        fh.write("\n")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
