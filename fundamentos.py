"""
Historia de ganancias y valuación de cada acción del monitor (balances presentados a la SEC).

Se corre una vez por semana (GitHub Actions, fundamentos.yml). Genera:
  - fund/<TICKER>.json : serie mensual de 15 años con precio, ganancia por acción de 12 meses (la conocida en
                         cada fecha), ganancia de los 12 meses siguientes (la que efectivamente llegó), ventas,
                         ganancia neta, flujo de caja libre, acciones en circulación y patrimonio.
  - fund_sum.json      : resumen por acción para filtrar y buscar en el monitor (P/E histórico y su rango,
                         crecimiento de 5 años, recompras, márgenes, etc.).

Los gráficos del monitor usan el precio de cada día de data.json, así que el "hoy" siempre está al día
aunque este archivo se actualice una vez por semana.
"""
import datetime as dt
import json
import os
import time

import numpy as np
import pandas as pd
import requests

SEC_UA = os.environ.get("SEC_UA") or "PROSPEI Monitor research github.com/finanzasconpedro-gif"
YEARS_PX = 16                 # años de precios (se muestran 15 y se usa 1 de margen)
STAT_YEARS = 10               # ventana para el rango histórico del P/E
OUT_DIR = "fund"
TIME_BUDGET = 100 * 60        # tope de minutos para bajar balances
T0 = time.time()
SEC_FAILS = [0]
BRK_RATIO = {"BRK-B": 1500}   # la SEC informa la ganancia por acción de la clase A


# ------------------------------------------------------------------ SEC
def sec_get(url, timeout=30):
    if SEC_FAILS[0] >= 8:
        raise RuntimeError("la SEC dejó de responder")
    for k in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=timeout)
        except requests.RequestException as e:
            SEC_FAILS[0] += 1
            if k == 2:
                raise RuntimeError(f"SEC sin respuesta: {e}")
            time.sleep(2 + 3 * k)
            continue
        if r.status_code == 200:
            SEC_FAILS[0] = 0
            return r
        if r.status_code == 403:
            raise RuntimeError("la SEC rechazó el pedido (403): falta el secreto SEC_UA")
        if r.status_code == 404:
            raise RuntimeError("sin datos en la SEC (404)")
        SEC_FAILS[0] += 1
        time.sleep(2 + 3 * k)
    r.raise_for_status()


def sec_ciks():
    r = sec_get("https://www.sec.gov/files/company_tickers.json")
    return {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in r.json().values()}


def sec_facts(cik):
    r = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", 90)
    time.sleep(0.15)          # la SEC pide no más de 10 consultas por segundo
    return r.json()


def _node(facts, tag, unit):
    return facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit)


def _derive(ent):
    """De los datos (inicio, fin) -> (valor, presentado) arma los trimestres: el informado, la diferencia entre
    acumulados del año (6 meses - 3, 9 - 6, anual - 9) o el anual menos los otros tres trimestres."""
    q = {en: (v, f) for (s, en), (v, f) in ent.items() if 80 <= (en - s).days <= 100}
    by_start = {}
    for (s, en), (v, f) in ent.items():
        by_start.setdefault(s, []).append((en, v, f))
    for s, L in by_start.items():
        L.sort()
        for (e1, v1, f1), (e2, v2, f2) in zip(L, L[1:]):
            if 80 <= (e2 - e1).days <= 100 and e2 not in q:
                q[e2] = (v2 - v1, max(f1, f2))
    for (s, en), (v, f) in ent.items():
        if 350 <= (en - s).days <= 380 and en not in q:
            ins = [q[k][0] for k in q if s - pd.Timedelta(days=7) <= k - pd.Timedelta(days=91) and k <= en - pd.Timedelta(days=60)]
            if len(ins) == 3:
                q[en] = (v - sum(ins), f)
    return q


def qseries(facts, tags, unit, adj=None):
    """Serie trimestral [(fin, presentado, valor)]. Toma siempre la primera vez que se publicó cada dato.
    Primero arma cada etiqueta por separado; los trimestres que falten (porque la empresa cambió de etiqueta
    entre los trimestres y el anual, algo muy común) se completan combinando todas las etiquetas."""
    best, merged = {}, {}
    for pri, tag in enumerate(tags):
        node = _node(facts, tag, unit)
        if not node:
            continue
        ent = {}
        for e in node:
            if "start" not in e or e.get("form", "")[:4] not in ("10-Q", "10-K"):
                continue
            s, en, f = pd.Timestamp(e["start"]), pd.Timestamp(e["end"]), pd.Timestamp(e["filed"])
            if (s, en) not in ent or f < ent[(s, en)][1]:
                v_ = float(e["val"])
                ent[(s, en)] = (adj(v_, f) if adj else v_, f)
        for k, v in ent.items():
            if k not in merged or merged[k][2] > pri:
                merged[k] = (v[0], v[1], pri)
        for en, (v, f) in _derive(ent).items():
            if en not in best or best[en][2] > pri:
                best[en] = (v, f, pri)
    if merged:
        for en, (v, f) in _derive({k: (v, f) for k, (v, f, _) in merged.items()}).items():
            if en not in best:
                best[en] = (v, f, 99)
    return sorted((en, f, v) for en, (v, f, _) in best.items())


def avg_series(facts, tags, unit, adj=None):
    """Promedios del período (acciones en circulación): no se pueden restar como las ventas. Se usa el trimestre
    informado y, para el 4º trimestre, el promedio anual."""
    best = {}
    for pri, tag in enumerate(tags):
        node = _node(facts, tag, unit)
        if not node:
            continue
        ent = {}
        for e in node:
            if "start" not in e or e.get("form", "")[:4] not in ("10-Q", "10-K"):
                continue
            s_, en, f = pd.Timestamp(e["start"]), pd.Timestamp(e["end"]), pd.Timestamp(e["filed"])
            d_ = (en - s_).days
            if not (80 <= d_ <= 100 or 350 <= d_ <= 380):
                continue
            k = (en, d_ < 200)
            if k not in ent or f < ent[k][1]:
                v_ = float(e["val"])
                ent[k] = (adj(v_, f) if adj else v_, f)
        for (en, isq), (v, f) in ent.items():
            if v <= 0:
                continue
            rank = (pri, 0 if isq else 1)
            if en not in best or best[en][2] > rank:
                best[en] = (v, f, rank)
    return sorted((en, f, v) for en, (v, f, _) in best.items())


def iseries(facts, tags, unit):
    """Serie de saldos al cierre de cada trimestre (patrimonio): [(fin, presentado, valor)]."""
    best = {}
    for pri, tag in enumerate(tags):
        node = _node(facts, tag, unit)
        if not node:
            continue
        for e in node:
            if "start" in e or e.get("form", "")[:4] not in ("10-Q", "10-K"):
                continue
            en, f = pd.Timestamp(e["end"]), pd.Timestamp(e["filed"])
            if (en - f).days > 0:
                continue
            cur = best.get(en)
            if cur is None or cur[2] > pri or (cur[2] == pri and f < cur[1]):
                best[en] = (float(e["val"]), f, pri)
    return sorted((en, f, v) for en, (v, f, _) in best.items())


def ttm(qs):
    """Suma de 4 trimestres consecutivos: [(fin, presentado, valor 12 meses)]."""
    out = []
    for i in range(3, len(qs)):
        w = qs[i - 3:i + 1]
        if 250 <= (w[-1][0] - w[0][0]).days <= 300:
            out.append((w[-1][0], max(x[1] for x in w), sum(x[2] for x in w)))
    return out


def known_at(series, dates):
    """Último valor ya presentado en cada fecha (lo que se sabía ese día)."""
    out = []
    j, cur = 0, np.nan
    s = sorted(series, key=lambda x: x[1])
    best_end = None
    for d in dates:
        while j < len(s) and s[j][1] <= d:
            if best_end is None or s[j][0] >= best_end:
                best_end, cur = s[j][0], s[j][2]
            j += 1
        out.append(cur if best_end is not None and (d - best_end).days <= 200 else np.nan)
    return np.array(out, dtype=float)


def forward_real(series, dates):
    """Ganancia de los 12 meses siguientes a cada fecha, la que efectivamente se informó después."""
    ends = [x[0] for x in series]
    vals = [x[2] for x in series]
    out = []
    for d in dates:
        tgt = d + pd.Timedelta(days=365)
        best, bd = np.nan, 47
        for en, v in zip(ends, vals):
            dd = abs((en - tgt).days)
            if dd < bd:
                best, bd = v, dd
        out.append(best)
    return np.array(out, dtype=float)


def split_factor(splits, filed, after=True):
    k = 1.0
    for d, r in splits or []:
        if d > filed:
            k *= r
    return k


# ------------------------------------------------------------------ armado por acción
EPS_T = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
REV_T = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenuesNetOfInterestExpense",
         "RevenueFromContractWithCustomerIncludingAssessedTax", "InterestAndDividendIncomeOperating"]
NI_T = ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"]
SH_T = ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"]
OCF_T = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX_T = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
EQ_T = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]


def build(sym, facts, px, splits):
    """px: serie mensual de cierres ajustados por splits (no por dividendos)."""
    dates = list(px.index)
    eps_adj = lambda v, f: v / split_factor(splits, f) / BRK_RATIO.get(sym, 1)
    sh_adj = lambda v, f: v * split_factor(splits, f) * BRK_RATIO.get(sym, 1)
    eps_q = qseries(facts, EPS_T, "USD/shares", eps_adj)
    rev_q = qseries(facts, REV_T, "USD")
    ni_q = qseries(facts, NI_T, "USD")
    ocf_q = qseries(facts, OCF_T, "USD")
    cap_q = qseries(facts, CAPEX_T, "USD")
    sh_q = avg_series(facts, SH_T, "shares", sh_adj)
    eq_i = iseries(facts, EQ_T, "USD")
    if len(eps_q) < 4 and len(rev_q) < 4:
        return None
    eps_t, rev_t, ni_t = ttm(eps_q), ttm(rev_q), ttm(ni_q)
    cap_by = {en: v for en, f, v in cap_q}
    fcf_qs = [(en, f, v - cap_by.get(en, 0.0)) for en, f, v in ocf_q]
    fcf_t = ttm(fcf_qs)
    M = 1e6
    if len(sh_q) < 4 and ni_q and eps_q:      # sin acciones informadas: ganancia neta / ganancia por acción
        eq_ = {en: v for en, f, v in eps_q if v}
        sh_q = [(en, f, abs(v / eq_[en])) for en, f, v in ni_q if en in eq_ and abs(eq_[en]) > 1e-6 and v * eq_[en] > 0]
    # control cruzado: la ganancia por acción informada tiene que coincidir con ganancia neta / acciones.
    # Si no coincide (datos mal etiquetados, splits o acciones en otra unidad), se usa ganancia neta / acciones.
    if ni_q and len(sh_q) >= 4:
        shd = {en: v for en, f, v in sh_q}
        epd = {en: (f, v) for en, f, v in eps_q}
        fixed = 0
        for en, f, v in ni_q:
            if en in shd and shd[en] > 0:
                alt = v / shd[en]
                cur = epd.get(en)
                if cur is None or (abs(alt) > 1e-3 and abs(cur[1] / alt - 1) > 0.4):
                    epd[en] = (cur[0] if cur else f, alt)
                    fixed += 1
        if fixed:
            eps_q = sorted((en, f, v) for en, (f, v) in epd.items())
    row = {
        "eps": known_at(eps_t, dates),
        "fe": forward_real(eps_t, dates),
        "rev": known_at(rev_t, dates) / M,
        "ni": known_at(ni_t, dates) / M,
        "fcf": known_at(fcf_t, dates) / M,
        "sh": known_at(sh_q, dates) / M,
        "bv": known_at(eq_i, dates) / M,
    }
    return row


def rnd(a, nd):
    return [None if x is None or not np.isfinite(x) else round(float(x), nd) for x in a]


def qtiles(x):
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    if len(x) < 12:
        return None
    return [round(float(np.percentile(x, q)), 2) for q in range(10, 100, 10)]


def summarize(p, row, dates):
    n = len(dates)
    k10 = max(0, n - 12 * STAT_YEARS)
    sl = slice(k10, n)
    eps, fe, rev, ni, sh, bv, fcf = (row[k] for k in ("eps", "fe", "rev", "ni", "sh", "bv", "fcf"))
    pe = np.where((eps > 0) & np.isfinite(p), p / np.where(eps > 0, eps, np.nan), np.nan)
    pe = np.where(pe < 200, pe, np.nan)
    pf = np.where((fe > 0) & np.isfinite(p), p / np.where(fe > 0, fe, np.nan), np.nan)
    pf = np.where(pf < 200, pf, np.nan)
    mcap = p * sh
    ps = np.where(rev > 0, mcap / np.where(rev > 0, rev, np.nan), np.nan)
    pb = np.where(bv > 0, mcap / np.where(bv > 0, bv, np.nan), np.nan)
    pb = np.where((pb > 0.05) & (pb < 60), pb, np.nan)

    def last(a):
        f = np.where(np.isfinite(a))[0]
        return float(a[f[-1]]) if len(f) else None

    def ago(a, m):
        i = n - 1 - m
        return float(a[i]) if 0 <= i < n and np.isfinite(a[i]) else None

    def cagr(a, b, yrs=5):
        if a is None or b is None or a <= 0 or b <= 0:
            return None
        return round((b / a) ** (1 / yrs) - 1, 4)

    e_now, e_5 = last(eps), ago(eps, 60)
    r_now, r_5 = last(rev), ago(rev, 60)
    s_now, s_5 = last(sh), ago(sh, 60)
    n_now, n_5 = last(ni), ago(ni, 60)
    f_now = last(fcf)
    p_now, p_5 = last(p), ago(p, 60)
    e_1 = ago(eps, 12)
    out = {
        "eps": e_now, "rev": r_now, "ni": n_now, "sh": s_now, "bv": last(bv), "fcf": f_now,
        "pe_q": qtiles(pe[sl]), "pe_n": int(np.isfinite(pe[sl]).sum()),
        "pf_q": qtiles(pf[sl]), "ps_q": qtiles(ps[sl]), "pb_q": qtiles(pb[sl]),
        "eps_c5": cagr(e_5, e_now), "rev_c5": cagr(r_5, r_now), "px_c5": cagr(p_5, p_now),
        "eps_g1": round(e_now / e_1 - 1, 4) if e_now and e_1 and e_1 > 0 and e_now > 0 else None,
        "sh_5": round(s_now / s_5 - 1, 4) if s_now and s_5 else None,
        "mg": round(n_now / r_now, 4) if n_now is not None and r_now else None,
        "mg5": round(n_5 / r_5, 4) if n_5 is not None and r_5 else None,
        "fcf_ni": round(f_now / n_now, 2) if f_now is not None and n_now and n_now > 0 else None,
        "neg_y": int(sum(1 for x in eps[sl][::12] if np.isfinite(x) and x <= 0)),
    }
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


# ------------------------------------------------------------------ principal
def main():
    import yfinance as yf
    rows = json.load(open("data.json", encoding="utf-8"))["rows"]
    tick = sorted({r["t"] for r in rows})
    print("Acciones:", len(tick))
    frames = []
    for i in range(0, len(tick), 100):
        frames.append(yf.download(tick[i:i + 100], period=f"{YEARS_PX}y", interval="1d", auto_adjust=False,
                                  actions=True, group_by="ticker", threads=True, progress=False))
        time.sleep(1)
    lv = lambda d: set(d.columns.get_level_values(0))
    px, splits = {}, {}
    for d in frames:
        for s in tick:
            if s not in lv(d):
                continue
            c = d[s]["Close"].dropna()
            if len(c) < 60:
                continue
            idx = c.index.tz_localize(None) if getattr(c.index, "tz", None) is not None else c.index
            c = pd.Series(c.values, index=idx)
            px[s] = c.resample("ME").last()
            if "Stock Splits" in d[s].columns:
                sp = d[s]["Stock Splits"].fillna(0)
                ev = [(pd.Timestamp(k).tz_localize(None) if pd.Timestamp(k).tzinfo else pd.Timestamp(k), float(v))
                      for k, v in sp[sp > 0].items() if float(v) != 1.0]
                if ev:
                    splits[s] = ev
    print("Con precios:", len(px))
    try:
        ciks = sec_ciks()
    except Exception as e:
        print("SEC no disponible:", e)
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    summ, done, miss = {}, 0, []
    # primero las que todavía no tienen historia (o la tienen más vieja): si se corta por tiempo, la próxima sigue
    age = lambda t: os.path.getmtime(os.path.join(OUT_DIR, f"{t}.json")) if os.path.exists(os.path.join(OUT_DIR, f"{t}.json")) else 0
    tick = sorted(tick, key=age)
    for n_t, s in enumerate(tick):
        if time.time() - T0 > TIME_BUDGET:
            print(f"Tope de tiempo en {n_t}/{len(tick)}: el resto queda con los datos de la corrida anterior")
            break
        cik = ciks.get(s.upper()) or ciks.get(s.upper().replace("-", "."))
        if not cik or s not in px:
            miss.append(s)
            continue
        try:
            facts = sec_facts(cik)
        except Exception as e:
            miss.append(s)
            if SEC_FAILS[0] >= 8:
                print("La SEC dejó de responder:", e)
                break
            continue
        p = px[s]
        row = build(s, facts, p, splits.get(s))
        if row is None:
            miss.append(s)
            continue
        dates = list(p.index)
        pa = p.values.astype(float)
        summ[s] = summarize(pa, row, dates)
        out = {"t": s, "d": [d.strftime("%Y-%m") for d in dates], "p": rnd(pa, 2),
               "eps": rnd(row["eps"], 3), "fe": rnd(row["fe"], 3), "rev": rnd(row["rev"], 1), "ni": rnd(row["ni"], 1),
               "fcf": rnd(row["fcf"], 1), "sh": rnd(row["sh"], 2), "bv": rnd(row["bv"], 1)}
        with open(os.path.join(OUT_DIR, f"{s}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"))
        done += 1
        if n_t % 50 == 0:
            print(f"  {n_t + 1}/{len(tick)} · {s}")
    # conserva el resumen anterior de las que no se pudieron actualizar esta vez
    try:
        old = json.load(open("fund_sum.json", encoding="utf-8")).get("rows", {})
        for k, v in old.items():
            summ.setdefault(k, v)
    except Exception:
        pass
    with open("fund_sum.json", "w", encoding="utf-8") as f:
        json.dump({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "stat_years": STAT_YEARS,
                   "rows": summ}, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"Historia de balances: {done} acciones · sin datos de la SEC: {len(miss)} ({', '.join(miss[:30])}{'…' if len(miss) > 30 else ''})")


if __name__ == "__main__":
    main()
