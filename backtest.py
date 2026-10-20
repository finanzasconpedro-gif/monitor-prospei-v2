"""
Track récord de la señal "Comprar hoy" del Monitor PROSPEI.

Mira hacia atrás 10 años (YEARS), día por día, en las 3 empresas de mayor capitalización de cada sector del S&P 500,
y registra cada vez que se dio la señal. Después mide qué pasó con el precio 3, 6 y 12 meses más tarde.

Todo es "punto en el tiempo": en cada fecha solo se usa información que existía ese día
(precios hasta esa fecha y balances ya presentados ante la SEC). Así se evita mirar el futuro.

Qué se puede reconstruir y qué no:
  - La parte técnica (puntaje AT, tendencia, Golden Cross, ruptura, corrección con rebote): exacta.
  - Fecha de balance (no comprar si presenta en 7 días): exacta (Yahoo; si falta, fecha de presentación a la SEC).
  - Fundamentos: aproximados con los balances históricos de la SEC (ganancia y ventas de 12 meses).
  - Precio objetivo de analistas, ganancia esperada y valor justo: NO existen gratis hacia atrás.
    Por eso el veredicto completo no se puede reproducir y se prueban dos variantes (ver VARIANTS).

Resultado: backtest.json (lo lee la página) y un resumen en el log de GitHub Actions.
"""
import datetime as dt
import json
import os
import time

import numpy as np
import pandas as pd
import requests

import screener as S

YEARS = 10                    # años de prueba (2016-2026: incluye 2018, el COVID en 2020 y 2022)
GAP = 20                      # ruedas sin señal para contar una señal nueva (evita contar la misma compra muchas veces)
H = {"3m": 63, "6m": 126, "12m": 252}
TARGET, STOP, TS_DAYS = 0.10, -0.08, 126
GOAL = 0.70
# La SEC exige identificarse con nombre y un email de contacto; si no, rechaza el pedido (error 403).
# Se carga como secreto del repositorio: Settings → Secrets and variables → Actions → SEC_UA
SEC_UA = os.environ.get("SEC_UA") or "PROSPEI Monitor research github.com/finanzasconpedro-gif"
BROAD_N, SEED, SEED2, SEED3, SEED4 = 100, 7, 11, 23, 31        # muestra amplia: 100 acciones al azar del S&P 500 (incluye las que anduvieron mal)
BRK_RATIO = {"BRK-B": 1500}   # la SEC informa la ganancia por acción clase A

FALLBACK = {   # por si no está data.json: 3 de mayor capitalización por sector (aprox.)
    "Tecnología": ["NVDA", "AAPL", "MSFT"], "Comunicaciones": ["GOOGL", "META", "NFLX"],
    "Consumo discrecional": ["AMZN", "TSLA", "HD"], "Financiero": ["BRK-B", "JPM", "V"],
    "Salud": ["LLY", "JNJ", "ABBV"], "Industrial": ["GE", "CAT", "RTX"],
    "Consumo básico": ["WMT", "COST", "PG"], "Energía": ["XOM", "CVX", "COP"],
    "Servicios públicos": ["NEE", "SO", "CEG"], "Inmobiliario": ["PLD", "AMT", "WELL"],
    "Materiales": ["LIN", "SHW", "NEM"]}

VARIANTS = {
    "A": "Técnica del monitor: puntaje técnico ≥ 65 + señal de entrada (corrección con rebote, Golden Cross o ruptura) + sin balance en 7 días",
    "B": "A + fundamentos básicos de ese momento: ganancia positiva, ventas creciendo y P/E no más de 10% arriba de su promedio de 5 años",
    "C": "A sin Golden Cross: solo corrección con rebote o ruptura de máximos",
    "D": "C + los mismos fundamentos de B (la regla propuesta para el monitor)",
    "E": "D + filtro de mercado: solo cuando el S&P 500 está arriba de su media de 200 días",
    "F": "C + crecimiento (ganancia y ventas de 12 meses creciendo contra el año anterior) + filtro de mercado",
    "G": "Solo corrección con señal de rebote (puntaje técnico ≥ 65, sin balance en 7 días): sin ruptura ni Golden Cross",
    "H": "G + momentum: la acción está entre el 30% del S&P 500 que más subió en 6 meses (sin contar el último mes)",
    "J": "H + crecimiento: además, ganancia y ventas de 12 meses creciendo contra el año anterior",
    "P": "Comprar en partes por giro temprano (parte técnica): viene cayendo y aparecen 4+ señales de giro, o Golden Cross en formación, o señal de entrada con puntaje técnico menor a 65; sin balance en 7 días",
    "Q": "P + los fundamentos de B (ganancia positiva, ventas creciendo, P/E no más de 10% arriba de su promedio de 5 años)",
    "R": "Comprar en partes por mercado bajista: cumple D pero el S&P 500 está debajo de su media de 200 días",
    "S": "Estrategia por sector: J en tecnología, industriales y comunicaciones · D en consumo discrecional · G en utilities, energía y materiales · sin señal en consumo básico, financiero, real estate y salud",
    "T": "Motor por sector del monitor (perfiles de screener.py): señal de entrada, momentum, crecimiento y peso de la valuación según el sector; sin señal en los sectores sin ventaja",
    "U": "P/E bajo contra su historia: P/E 30% o más por debajo de su mediana de 5 años (ganancia positiva), sin señal técnica; sin balance en 7 días",
    "V": "P/E muy bajo contra su historia: P/E 50% o más por debajo de su mediana de 5 años (ganancia positiva), sin señal técnica; sin balance en 7 días",
    "W": "U + crecimiento: P/E 30%+ debajo de su historia con ganancia y ventas de 12 meses creciendo contra el año anterior",
    "X": "U + rebote: P/E 30%+ debajo de su historia y además corrección con señal de rebote (puntaje técnico ≥ 65)",
}
VARIANTS.pop("_", None)
KEYS = ("A", "B", "C", "D", "E", "F", "G", "H", "J", "P", "Q", "R", "S", "T", "U", "V", "W", "X")
PE_CHEAP, PE_DEEP = 0.70, 0.50   # P/E contra su mediana de 5 años para las variantes U-X
S_MAP = {"Tecnología": "J", "Industrial": "J", "Comunicaciones": "J", "Consumo discrecional": "D",
         "Utilities": "G", "Servicios públicos": "G", "Energía": "G", "Materiales": "G"}
# ---- señales de agotamiento: qué pasó en los 30, 60 y 90 días siguientes (21, 42 y 63 ruedas)
XH = {"30d": 21, "60d": 42, "90d": 63}
ALERTS = {
    "rsi75": "Sobrecompra: RSI de 14 días en 75 o más",
    "rsi80": "Sobrecompra extrema: RSI en 80 o más",
    "ext30": "Precio estirado: 30% o más arriba de su media de 200 días",
    "ext50": "Precio muy estirado: 50% o más arriba de su media de 200 días",
    "pe90": "P/E caro contra su historia: en el 10% más alto de sus últimos 5 años",
    "run": "El precio corrió más que las ganancias: subió 40% o más en 12 meses y la ganancia creció menos de 10%",
    "div": "Divergencia bajista: precio en máximos de 52 semanas pero el RSI no acompaña (venía de 72+ y hoy está debajo de 65)",
    "epsdn": "Ganancias en baja con el precio en máximos (a menos de 3% del máximo de 52 semanas)",
    "pe90_rsi": "Combinada: P/E caro contra su historia + RSI en 70 o más",
    "ext30_rsi": "Combinada: precio estirado 30%+ sobre la media de 200 + RSI en 70 o más",
    "two": "Dos o más señales de agotamiento al mismo tiempo",
}
CONV_D = 63      # ventana para ver si un "Comprar en partes" pasa a señal de Comprar (3 meses)
SPLIT = "2022-01-01"   # diseño: antes de esta fecha · validación: desde esta fecha
MOM_MIN = 0.70
EXIT_H = 252     # se compara cada regla de venta contra mantener 12 meses
EXIT_RULES = {
    "stop10": "Stop fijo: vender si pierde 10% desde la compra",
    "stop10t": "Stop 10% solo si además la tendencia no acompaña (regla de Mi cartera)",
    "hard20": "Pérdida máxima: vender si pierde 20%",
    "trail15": "Stop que acompaña: vender si cae 15% desde el máximo posterior a la compra",
    "trail15m": "Cae 15% desde el máximo y además pierde la media de 200 (regla de Mi cartera)",
    "bear": "Tendencia de largo plazo bajista confirmada (regla de Mi cartera)",
    "risk2": "Riesgo de baja: 2 de 3 señales técnicas (tendencia bajista, perforó mínimo, Death Cross)",
    "cartera": "Todas las reglas de Vender de Mi cartera juntas (la primera que se active)",
    "cartera_r": "Mi cartera + riesgo de baja",
    "fund": "Fundamentos: la ganancia de 12 meses cae contra el año anterior en dos trimestres seguidos (o pasa a pérdida)",
    "fund_t": "Fundamentos en baja + tendencia bajista juntos (propuesta para Vender en Mi cartera)",
}
# reglas originales del monitor (la A incluye el Golden Cross; el monitor ya lo sacó en base a esta prueba)
ENTRY_A = {"Corrección con señal de rebote", "Golden Cross", "Ruptura de máximos"}


# ------------------------------------------------------------------ universo
def pick_universes():
    """top: las 3 más grandes de cada sector. broad: 100 al azar del S&P 500, repartidas por sector."""
    top = pick_universe()
    tops = {t for v in top.values() for t in v}
    broad = {}
    try:
        rows = json.load(open("data.json", encoding="utf-8"))["rows"]
        df = pd.DataFrame([{"t": r["t"], "sector": r["sector"], "region": r.get("region")} for r in rows])
        df = df[(df.region == "EE.UU.") & ~df.t.isin(tops)]
        frac = min(1.0, BROAD_N / len(df))
        for sec, g in df.groupby("sector"):
            broad[sec] = sorted(g.sample(min(len(g), max(1, round(len(g) * frac))), random_state=SEED).t)
    except Exception as e:
        print("Sin muestra amplia (falta data.json):", e)
    # muestra de control: otras 100 acciones distintas, nunca usadas para elegir reglas
    broad2 = {}
    try:
        used = tops | {t for v in broad.values() for t in v}
        df2 = df[~df.t.isin(used)]
        frac2 = min(1.0, BROAD_N / max(1, len(df2)))
        for sec, g in df2.groupby("sector"):
            broad2[sec] = sorted(g.sample(min(len(g), max(1, round(len(g) * frac2))), random_state=SEED2).t)
    except Exception as e:
        print("Sin muestra de control:", e)
    # tercera muestra: para validar la estrategia por sector (S), que se eligió mirando las dos anteriores
    broad3 = {}
    try:
        used3 = used | {t for v in broad2.values() for t in v}
        df3 = df[~df.t.isin(used3)]
        frac3 = min(1.0, BROAD_N / max(1, len(df3)))
        for sec, g in df3.groupby("sector"):
            broad3[sec] = sorted(g.sample(min(len(g), max(1, round(len(g) * frac3))), random_state=SEED3).t)
    except Exception as e:
        print("Sin tercera muestra:", e)
    # cuarta muestra: todas las acciones de EE.UU. que no se usaron en ninguna prueba (valida el motor por sector, T)
    broad4 = {}
    try:
        used4 = used3 | {t for v in broad3.values() for t in v}
        for sec, g in df[~df.t.isin(used4)].groupby("sector"):
            broad4[sec] = sorted(g.t)
    except Exception as e:
        print("Sin cuarta muestra:", e)
    return {"top": top, "broad": broad, "broad2": broad2, "broad3": broad3, "broad4": broad4}


def pick_universe():
    try:
        rows = json.load(open("data.json", encoding="utf-8"))["rows"]
        df = pd.DataFrame([{"t": r["t"], "sector": r["sector"], "mcap": r.get("mcap") or 0, "region": r.get("region")}
                           for r in rows])
        df = df[(df.region == "EE.UU.") & (df.mcap > 0)]
        out = {}
        for sec, g in df.sort_values("mcap", ascending=False).groupby("sector"):
            out[sec] = list(g.t.head(3))
        if sum(len(v) for v in out.values()) >= 25:
            return out
    except Exception as e:
        print("No pude leer data.json, uso lista fija:", e)
    return FALLBACK


# ------------------------------------------------------------------ SEC (balances punto en el tiempo)
SEC_FAILS = [0]          # fallas seguidas: si la SEC deja de responder, se sigue sin balances en vez de trabarse
T0 = time.time()
TIME_BUDGET_FUND = 90 * 60   # tope de minutos para bajar balances; después se sigue con lo que haya


def sec_get(url, timeout=25):
    if SEC_FAILS[0] >= 8:
        raise RuntimeError("la SEC dejó de responder: se sigue sin balances")
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
            raise RuntimeError("la SEC rechazó el pedido (403): falta cargar el secreto SEC_UA con nombre y email de contacto")
        if r.status_code == 404:
            raise RuntimeError("sin datos en la SEC (404)")
        SEC_FAILS[0] += 1
        time.sleep(2 + 3 * k)
    r.raise_for_status()


def sec_ciks():
    r = sec_get("https://www.sec.gov/files/company_tickers.json", 30)
    return {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in r.json().values()}


def sec_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    r = sec_get(url)
    time.sleep(0.15)          # la SEC pide no más de 10 consultas por segundo
    return r.json()


def quarters(facts, tags, unit, adj=None):
    """Serie trimestral (fin, fecha de presentación, valor). El 4º trimestre se deriva del anual menos 3 trimestres."""
    best = {}
    for pri, tag in enumerate(tags):
        node = facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit)
        if not node:
            continue
        ent = {}
        for e in node:
            if "start" not in e or e.get("form", "")[:4] not in ("10-Q", "10-K"):
                continue
            s, en, f = pd.Timestamp(e["start"]), pd.Timestamp(e["end"]), pd.Timestamp(e["filed"])
            k = (s, en)
            if k not in ent or f < ent[k][1]:          # la primera vez que se publicó (sin revisiones posteriores)
                v_ = float(e["val"])
                ent[k] = (adj(v_, f) if adj else v_, f)
        qs = {k: v for k, v in ent.items() if 80 <= (k[1] - k[0]).days <= 100}
        ys = {k: v for k, v in ent.items() if 350 <= (k[1] - k[0]).days <= 380}
        q = {en: (val, f) for (s, en), (val, f) in qs.items()}
        for (s, en), (val, f) in ys.items():
            ins = [v for (qs_, qe), v in qs.items() if qs_ >= s - pd.Timedelta(days=7) and qe <= en - pd.Timedelta(days=60)]
            if len(ins) == 3 and en not in q:
                q[en] = (val - sum(x[0] for x in ins), f)
        for en, v in q.items():
            if en not in best or best[en][2] > pri:
                best[en] = (v[0], v[1], pri)
    return sorted((en, f, v) for en, (v, f, _) in best.items())


def ttm_daily(qs, index):
    """Valor de 12 meses conocido en cada fecha del índice (solo trimestres ya presentados)."""
    if len(qs) < 4:
        return pd.Series(np.nan, index=index)
    out = []
    for d in index:
        known = [(en, v) for en, f, v in qs if f <= d]
        known = known[-4:]
        if len(known) == 4 and 250 <= (known[-1][0] - known[0][0]).days <= 300:
            out.append(sum(v for _, v in known))
        else:
            out.append(np.nan)
    return pd.Series(out, index=index)


def split_adj(splits):
    """La SEC publica la ganancia por acción con la cantidad de acciones de ese momento. Los precios de Yahoo
    vienen ajustados por todos los splits posteriores, así que la ganancia se divide por los splits
    ocurridos después de cada presentación (ej. NVDA 4:1 en 2021 y 10:1 en 2024)."""
    if not splits:
        return None
    def f(val, filed):
        k = 1.0
        for d, r in splits:
            if d > filed:
                k *= r
        return val / k
    return f


def fundamentals(sym, cik, close, splits=None):
    """Devuelve DataFrame diario con eps_ttm, pe, pe_med5 (mediana de 5 años previa), rev_g y fechas de presentación."""
    idx = close.index
    try:
        f = sec_facts(cik)
    except Exception as e:
        print("  SEC sin datos para", sym, e)
        return None, []
    eps_q = quarters(f, ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"], "USD/shares",
                     split_adj(splits))
    rev_q = quarters(f, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                         "RevenuesNetOfInterestExpense", "RevenueFromContractWithCustomerIncludingAssessedTax"], "USD")
    # muestreo semanal para acelerar y luego se rellena
    wk = idx[::5]
    eps = ttm_daily(eps_q, wk).reindex(idx, method="ffill") / BRK_RATIO.get(sym, 1)
    rev = ttm_daily(rev_q, wk).reindex(idx, method="ffill")
    pe = (close / eps).where(eps > 0)
    pe_med5 = pe.rolling(1260, min_periods=500).median().shift(1)
    rev_g = rev / rev.shift(252) - 1
    eps_prev = eps.shift(252)
    eps_g = (eps / eps_prev - 1).where((eps > 0) & (eps_prev > 0))
    filed = sorted({f for _, f, _ in eps_q})
    return pd.DataFrame({"eps": eps, "pe": pe, "pe_med5": pe_med5, "rev_g": rev_g, "eps_g": eps_g}), filed


def sec_earn_dates(cik):
    """Fechas de publicación de resultados: formularios 8-K con el ítem 2.02 (Results of Operations)."""
    try:
        r = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", 30).json()
        time.sleep(0.12)
        pages = [r.get("filings", {}).get("recent", {})]
        # las empresas grandes tienen miles de presentaciones: las más viejas están en archivos aparte
        lim = (pd.Timestamp.today() - pd.DateOffset(years=YEARS + 1)).strftime("%Y-%m-%d")
        for fobj in r.get("filings", {}).get("files", []):
            if str(fobj.get("filingTo", "9999")) >= lim:
                try:
                    pages.append(sec_get(f"https://data.sec.gov/submissions/{fobj['name']}", 30).json())
                    time.sleep(0.12)
                except Exception:
                    pass
        out = set()
        for rec in pages:
            out |= {pd.Timestamp(d) for f, d, it in zip(rec.get("form", []), rec.get("filingDate", []), rec.get("items", []))
                    if f == "8-K" and "2.02" in str(it)}
        return sorted(out)
    except Exception:
        return []


def earnings_dates(sym, filed, cik=None):
    if cik:
        d = sec_earn_dates(cik)
        if len(d) >= 8:
            return d
    if cik and filed:
        return [pd.Timestamp(d) for d in filed]
    try:
        import yfinance as yf
        ed = yf.Ticker(sym).get_earnings_dates(limit=40)
        if ed is not None and len(ed):
            return sorted({pd.Timestamp(d).tz_localize(None).normalize() for d in ed.index})
    except Exception:
        pass
    return [pd.Timestamp(d) for d in filed]


# ------------------------------------------------------------------ puntaje técnico (idéntico al del screener)
def score_tech_pit(df, mom_pct):
    t = pd.Series(0.0, index=df.index)
    t += df.trend_n.map({2: 10, 1: 6, 0: 4, -1: 2, -2: 0}).fillna(4)
    t += np.where(df.sma50 > df.sma200, 10, 0)
    t += np.where(df.sma200_up, 10, 0)
    t += np.where(df.et_ctx, 1.5 * df.et_n, 0)
    t += df.cross.map({"Golden Cross reciente": 3, "Golden Cross en formación": 2,
                       "Death Cross reciente": -3, "Death Cross en formación": -2}).fillna(0)
    t += 25 * mom_pct.fillna(0.3)
    r = df.rsi
    t += np.select([(r >= 40) & (r <= 60), (r > 60) & (r <= 70), (r >= 30) & (r < 40), r < 30, r > 70],
                   [15, 10, 11, 7, 3], 5)
    t += np.where(df.macd_h > 0, 5, 0) + np.where(df.macd_up, 2, 0) + np.where(df.macd_cross, 3, 0)
    up = df.trend_n >= 1
    dd = df.dd
    t += np.select([up & (dd <= -0.05) & (dd >= -0.20), up & (dd > -0.05), up & (dd < -0.20)], [20, 15, 10], 4)
    return t.clip(0, 100)


# ------------------------------------------------------------------ estadísticas
def stats(rows, key):
    v = [r for r in rows if r.get(key) is not None]
    if not v:
        return {"n": 0}
    x = np.array([r[key] for r in v])
    out = {"n": len(v), "win": float((x > 0).mean()), "avg": float(x.mean()), "med": float(np.median(x)),
           "p10": float(np.percentile(x, 10)), "l20": float((x <= -0.20).mean())}
    b = [r[key] - r["spy_" + key] for r in v if r.get("spy_" + key) is not None]
    if b:
        out["beat"] = float((np.array(b) > 0).mean())
        out["alpha"] = float(np.mean(b))
    return out


def ts_stats(rows):
    v = [r["ts"] for r in rows if r.get("ts")]
    if not v:
        return {"n": 0}
    return {"n": len(v), "target": v.count("objetivo") / len(v), "stop": v.count("stop") / len(v),
            "open": v.count("abierta") / len(v)}


def summarize(rows):
    return {**{h: stats(rows, h) for h in H}, "ts": ts_stats(rows)}


TECH_COLS = ["p", "sma50", "sma200", "sma200_up", "trend_n", "dd", "dd3", "rsi", "macd_h", "macd_up", "macd_cross",
             "r1m", "r6m", "vol_ratio", "recovery", "rebound", "et_hl", "et_div", "et_acc", "et_brk", "et_mom"]
CROSS = [None, "Golden Cross reciente", "Golden Cross en formación", "Death Cross reciente", "Death Cross en formación"]


def run_ticker(args):
    """Corre la prueba completa para una acción (en un proceso aparte). Devuelve episodios por variante,
    muestra de "cualquier día" y los datos para el gráfico."""
    t, c, v, spy, mom, days, dates, ed, fd, mkt, sector = args
    rows, keep = [], []
    for i in days:
        lo = max(0, i - 1100)
        cc, vv = c[lo:i + 1], v[lo:i + 1]
        ok = np.isfinite(cc)
        if ok.sum() < 260 or not np.isfinite(c[i]):
            continue
        r = S.technical(cc[ok], vv[ok])
        if not r:
            continue
        row = {k: r.get(k) for k in TECH_COLS}
        row["cross"] = r.get("cross")
        row["et_low"] = r.get("et_low")
        row["slope200_pct"] = r.get("slope200_pct")
        rows.append(row)
        keep.append(i)
    if not rows:
        return t, None
    df = pd.DataFrame(rows, index=keep)
    for k in TECH_COLS:
        df[k] = pd.to_numeric(df[k], errors="coerce") if k not in ("sma200_up", "macd_up", "macd_cross", "recovery", "rebound",
                                                                  "et_hl", "et_div", "et_acc", "et_brk", "et_mom") else df[k].fillna(False).astype(bool)
    ki = np.array(keep)
    spy_r1m = spy[ki] / spy[ki - 21] - 1
    df["et_rs"] = (df.r1m.values - spy_r1m) > 0
    df["et_n"] = df[["et_hl", "et_div", "et_acc", "et_brk", "et_mom", "et_rs"]].astype(bool).sum(axis=1)
    df["et_ctx"] = (df.trend_n <= 0) & (df.dd <= -0.05)
    df["at"] = score_tech_pit(df, pd.Series(mom[ki], index=df.index))
    df["af"] = 0
    df["setup"] = [S.setup(r) for r in df.itertuples()]
    n = len(c)
    eps = {k: [] for k in KEYS}
    base = []
    last = {}
    sigC = np.zeros(n, dtype=bool)
    sigD = np.zeros(n, dtype=bool)
    pidx = {"P": [], "Q": []}
    for i, r in zip(ki, df.itertuples()):
        if i + 1 >= n:
            continue
        d = np.datetime64(dates[i])
        earn = bool(len(ed) and ((ed > d) & (ed <= d + np.timedelta64(7, "D"))).any())
        a = bool(r.at >= S.V_AT and r.setup in ENTRY_A and not earn)
        b = False
        if a and fd is not None:
            e, pe, med, g = fd[0][i], fd[1][i], fd[2][i], fd[3][i]
            b = bool(np.isfinite(e) and e > 0 and np.isfinite(g) and g > 0 and np.isfinite(pe) and np.isfinite(med) and pe <= med * 1.10)
        cc_ = a and r.setup != "Golden Cross"
        up = bool(mkt[i])
        grow = False
        if cc_ and fd is not None:
            eg, rg = fd[4][i], fd[3][i]
            grow = bool(np.isfinite(eg) and eg > 0 and np.isfinite(rg) and rg > 0)
        g_ = bool(r.at >= S.V_AT and r.setup == "Corrección con señal de rebote" and not earn)
        h_ = bool(g_ and np.isfinite(mom[i]) and mom[i] >= MOM_MIN)
        g2 = False
        if h_ and fd is not None:
            eg, rg = fd[4][i], fd[3][i]
            g2 = bool(np.isfinite(eg) and eg > 0 and np.isfinite(rg) and rg > 0)
        # "Comprar en partes" por giro temprano (camino 4 del veredicto): solo lo que se puede reconstruir
        early = bool((r.et_ctx and r.et_n >= 4) or r.setup == "Golden Cross en formación")
        entry_lo = r.setup in ("Corrección con señal de rebote", "Ruptura de máximos") and r.at < S.V_AT
        p_ = bool((early or entry_lo) and not earn)
        fb = False
        if p_ and fd is not None:
            e, pe, med, g = fd[0][i], fd[1][i], fd[2][i], fd[3][i]
            fb = bool(np.isfinite(e) and e > 0 and np.isfinite(g) and g > 0 and np.isfinite(pe) and np.isfinite(med) and pe <= med * 1.10)
        # fundamentos de B calculados aunque la técnica no dé (para saber si un Q pasa a Comprar D)
        fbd = b
        sigC[i] = cc_
        sigD[i] = bool(fbd and cc_)
        sig = {"A": a, "B": b, "C": cc_, "D": b and cc_, "E": b and cc_ and up, "F": grow and up,
               "G": g_, "H": h_, "J": g2, "P": p_, "Q": p_ and fb, "R": b and cc_ and not up}
        sig["S"] = bool(sig.get(S_MAP.get(sector, "_"), False))
        # T: el motor por sector del monitor (mismos perfiles que screener.py)
        PF = getattr(S, "SECTOR_PROFILE", {}).get(sector)
        t_ = False
        if PF and PF["edge"] and r.at >= S.V_AT and r.setup in PF["entry"] and not earn:
            t_ = True
            if PF["mom"] is not None:
                t_ = t_ and np.isfinite(mom[i]) and mom[i] >= PF["mom"]
            if PF["growth"] or PF["val"] == "full":
                if fd is None:
                    t_ = False
                else:
                    e, pe, med, g, eg = fd[0][i], fd[1][i], fd[2][i], fd[3][i], fd[4][i]
                    if PF["growth"]:
                        t_ = t_ and bool(np.isfinite(eg) and eg > 0 and np.isfinite(g) and g > 0)
                    if PF["val"] == "full":
                        t_ = t_ and bool(np.isfinite(e) and e > 0 and np.isfinite(g) and g > 0 and np.isfinite(pe) and np.isfinite(med) and pe <= med * 1.10)
        sig["T"] = bool(t_)
        # U-X: P/E bajo contra su propia historia (la tesis "está barata contra su historia")
        pe_r = np.nan
        if fd is not None:
            e, pe, med = fd[0][i], fd[1][i], fd[2][i]
            if np.isfinite(e) and e > 0 and np.isfinite(pe) and pe > 0 and np.isfinite(med) and med > 0:
                pe_r = pe / med
        u_ = bool(np.isfinite(pe_r) and pe_r <= PE_CHEAP and not earn)
        sig["U"] = u_
        sig["V"] = bool(u_ and pe_r <= PE_DEEP)
        w_ = False
        if u_:
            eg, rg = fd[4][i], fd[3][i]
            w_ = bool(np.isfinite(eg) and eg > 0 and np.isfinite(rg) and rg > 0)
        sig["W"] = w_
        sig["X"] = bool(u_ and g_)
        new = {k: sig[k] and i - last.get(k, -999) > GAP for k in sig}
        if i % 5 == 0 or any(new.values()):
            p0 = c[i + 1]
            res = {"date": str(dates[i])[:10], "setup": r.setup, "at": round(float(r.at)), "p": round(float(p0), 2)}
            for h, hn in H.items():
                if i + 1 + hn < n and np.isfinite(c[i + 1 + hn]):
                    res[h] = float(c[i + 1 + hn] / p0 - 1)
                    res["spy_" + h] = float(spy[i + 1 + hn] / spy[i + 1] - 1)
            path = c[i + 2:i + 2 + TS_DAYS] / p0 - 1
            ht = int(np.argmax(path >= TARGET)) if (path >= TARGET).any() else None
            hs = int(np.argmax(path <= STOP)) if (path <= STOP).any() else None
            if ht is not None and (hs is None or ht < hs):
                res["ts"] = "objetivo"
            elif hs is not None:
                res["ts"] = "stop"
            elif len(path) >= TS_DAYS:
                res["ts"] = "abierta"
            res["year"] = res["date"][:4]
            if i % 5 == 0:
                base.append(res)
            for k in sig:
                if new[k]:
                    eps[k].append(dict(res, b=b, c=cc_, d=b and cc_, m=up, g=grow))
                    if k in pidx:
                        pidx[k].append((i, len(eps[k]) - 1))
        for k in sig:
            if sig[k]:
                last[k] = i
    # ---- señales de agotamiento: qué pasó a 30, 60 y 90 días
    alerts, xbase = {k: [] for k in ALERTS}, []
    try:
        rsi = df.rsi.values.astype(float)
        ext = (df.p / df.sma200 - 1).values.astype(float)
        ddv = df.dd.values.astype(float)
        rmax = pd.Series(rsi).rolling(60, min_periods=20).max().shift(1).values
        r12 = np.array([c[i] / c[i - 252] - 1 if i >= 252 and np.isfinite(c[i - 252]) and c[i - 252] > 0 else np.nan for i in ki])
        if fd is not None:
            pe_all = pd.Series(np.where(fd[1] > 0, fd[1], np.nan))
            perank = pe_all.rolling(1260, min_periods=500).rank(pct=True).values[ki]
            epsg = fd[4][ki]
        else:
            perank = np.full(len(ki), np.nan)
            epsg = np.full(len(ki), np.nan)
        ge = lambda a, x: np.isfinite(a) & (a >= x)
        f_ = {
            "rsi75": ge(rsi, 75), "rsi80": ge(rsi, 80), "ext30": ge(ext, 0.30), "ext50": ge(ext, 0.50),
            "pe90": ge(perank, 0.90),
            "run": ge(r12, 0.40) & np.isfinite(epsg) & (epsg < 0.10),
            "div": (ddv > -0.02) & np.isfinite(rmax) & (rmax >= 72) & np.isfinite(rsi) & (rsi < 65),
            "epsdn": np.isfinite(epsg) & (epsg < 0) & (ddv > -0.03),
        }
        f_["pe90_rsi"] = f_["pe90"] & ge(rsi, 70)
        f_["ext30_rsi"] = f_["ext30"] & ge(rsi, 70)
        f_["two"] = (f_["rsi75"].astype(int) + f_["ext30"] + f_["pe90"] + f_["run"] + f_["div"] + f_["epsdn"]) >= 2
        lastx = {}
        for j, i in enumerate(ki):
            if i + 1 + 63 >= n or not np.isfinite(c[i + 1]):
                continue
            hit = [k for k in ALERTS if f_[k][j] and i - lastx.get(k, -999) > GAP]
            for k in ALERTS:
                if f_[k][j]:
                    lastx[k] = i
            if not hit and i % 5:
                continue
            p0 = c[i + 1]
            ev = {"date": str(dates[i])[:10]}
            for hk, hn in XH.items():
                seg = c[i + 2:i + 2 + hn]
                seg = seg[np.isfinite(seg)]
                if not np.isfinite(c[i + 1 + hn]) or not len(seg):
                    ev = None
                    break
                ev["r" + hk] = float(c[i + 1 + hn] / p0 - 1)
                ev["m" + hk] = float(seg.min() / p0 - 1)
                ev["s" + hk] = float(spy[i + 1 + hn] / spy[i + 1] - 1)
            if ev is None:
                continue
            if i % 5 == 0:
                xbase.append(ev)
            for k in hit:
                alerts[k].append(ev)
    except Exception as e:
        print("  agotamiento sin calcular para", t, e)
    # ---- ¿el "Comprar en partes" pasa a Comprar? (P -> técnica de Comprar C; Q -> Comprar con fundamentos D)
    conv = {}
    for k, target in (("P", sigC), ("Q", sigD)):
        out_ = []
        for i, j in pidx[k]:
            e = eps[k][j]
            w = target[i + 1:min(n, i + 1 + CONV_D)]
            hit = int(np.argmax(w)) + 1 if w.any() else None
            x = {"date": e["date"], "6m": e.get("6m"), "spy_6m": e.get("spy_6m"), "conv": hit is not None}
            if hit is not None and i + hit + 1 < n:
                p1 = c[i + hit + 1]
                x["days"] = hit
                x["wait"] = float(p1 / c[i + 1] - 1)                        # cuánto se movió mientras esperaba
                if i + hit + 1 + 126 < n:
                    x["c6m"] = float(c[i + hit + 1 + 126] / p1 - 1)      # 6 meses comprando recién al pasar a Comprar
            out_.append(x)
        conv[k] = out_
    # ---- reglas de venta: para cada compra C (técnica sin Golden Cross), qué pasa con cada regla vs mantener 12 meses
    N_ = len(c)
    arr = lambda col: np.full(N_, np.nan)
    tn, s50, s200, elow, slp = arr(0), arr(0), arr(0), arr(0), arr(0)
    dcross = np.zeros(N_, dtype=bool)
    tn[ki] = df.trend_n.values
    s50[ki] = df.sma50.values
    s200[ki] = df.sma200.values
    elow[ki] = pd.to_numeric(df.et_low, errors="coerce").values
    slp[ki] = pd.to_numeric(df.slope200_pct, errors="coerce").values
    dcross[ki] = df.cross.isin(["Death Cross reciente", "Death Cross en formación"]).values
    # deterioro de fundamentos: ganancia 12m cae contra el año anterior (o pasa a pérdida), en dos trimestres seguidos
    det = np.zeros(N_, dtype=bool)
    if fd is not None:
        e0 = fd[0]
        prev = np.r_[np.full(252, np.nan), e0[:-252]] if N_ > 252 else np.full(N_, np.nan)
        bad = ((np.isfinite(fd[4]) & (fd[4] < 0)) | (np.isfinite(e0) & (e0 <= 0) & np.isfinite(prev) & (prev > 0)))
        bad_q = np.r_[np.zeros(63, dtype=bool), bad[:-63]] if N_ > 63 else np.zeros(N_, dtype=bool)
        det = bad & bad_q
    exits = []
    for e in eps["C"]:
        i0 = int(np.searchsorted(dates, np.datetime64(e["date"])))
        if i0 + 1 + EXIT_H >= N_:
            continue
        p0 = c[i0 + 1]
        hold = c[i0 + 1 + EXIT_H] / p0 - 1
        out = {"date": e["date"], "hold": float(hold), "hold6": float(c[i0 + 1 + 126] / p0 - 1)}
        done = {}
        mx = p0
        for j in range(i0 + 2, i0 + 1 + EXIT_H):
            pj = c[j]
            if not np.isfinite(pj):
                continue
            mx = max(mx, pj)
            r_, dd_ = pj / p0 - 1, pj / mx - 1
            t_ = tn[j]
            below200 = np.isfinite(s200[j]) and pj < s200[j]
            risk = int(np.isfinite(t_) and t_ <= -1) + int(np.isfinite(elow[j]) and pj < elow[j] * 0.99) + \
                int(dcross[j] or (np.isfinite(s50[j]) and np.isfinite(s200[j]) and s50[j] < s200[j] and np.isfinite(slp[j]) and slp[j] < -0.005))
            fire = {"stop10": r_ <= -0.10, "stop10t": r_ <= -0.10 and np.isfinite(t_) and t_ <= 0, "hard20": r_ <= -0.20,
                    "trail15": dd_ <= -0.15, "trail15m": dd_ <= -0.15 and below200, "bear": np.isfinite(t_) and t_ == -2,
                    "risk2": risk >= 2}
            fire["cartera"] = fire["stop10t"] or fire["hard20"] or fire["trail15m"] or fire["bear"]
            fire["cartera_r"] = fire["cartera"] or fire["risk2"]
            fire["fund"] = bool(det[j])
            fire["fund_t"] = bool(det[j]) and np.isfinite(t_) and t_ <= -1
            for k_, f_ in fire.items():
                if f_ and k_ not in done:
                    px = c[j + 1] if np.isfinite(c[j + 1]) else pj      # se vende al cierre del día siguiente
                    done[k_] = (float(px / p0 - 1), j + 1 - (i0 + 1))
            if len(done) == len(EXIT_RULES):
                break
        for k_ in EXIT_RULES:
            out[k_] = done.get(k_, (float(hold), None))
        exits.append(out)
    return t, {"eps": eps, "base": base, "exits": exits, "conv": conv, "alerts": alerts, "xbase": xbase}


def split_stats(rows):
    d = [r for r in rows if r["date"] < SPLIT]
    v = [r for r in rows if r["date"] >= SPLIT]
    return {"d": {h: stats(d, h) for h in ("6m", "12m")}, "v": {h: stats(v, h) for h in ("6m", "12m")}}


def by(rows, field):
    g = {}
    for r in rows:
        g.setdefault(r[field], []).append(r)
    return {k: {"n": len(v), **{h: stats(v, h) for h in ("6m", "12m")}} for k, v in sorted(g.items())}


UNI_LBL = {"top": "Las 3 más grandes de cada sector", "broad": f"Muestra amplia: {BROAD_N} acciones al azar del S&P 500",
           "broad2": f"Muestra de control: otras {BROAD_N} acciones (nunca usadas para elegir reglas)",
           "broad3": f"Validación de la estrategia por sector: otras {BROAD_N} acciones nuevas",
           "broad4": "Validación del motor por sector: todas las acciones que no se usaron en ninguna prueba"}


def all_tickers():
    """Todas las acciones del monitor (S&P 500 + ADRs) con nombre y sector."""
    try:
        rows = json.load(open("data.json", encoding="utf-8"))["rows"]
        return {r["t"]: (r.get("name") or r["t"], r.get("sector") or "", r.get("region") or "") for r in rows}
    except Exception:
        return {s: (n, S.SECTOR_ES.get(g, g), "EE.UU.") for s, n, g in S.sp500()}


def main():
    import yfinance as yf
    from concurrent.futures import ProcessPoolExecutor
    unis = pick_universes()
    meta = all_tickers()
    for u in unis.values():
        for sname, v in u.items():
            for t in v:
                meta.setdefault(t, (t, sname, "EE.UU."))
    tick = sorted(meta)
    member = {k: {t for v in u.values() for t in v} for k, u in unis.items()}
    print("Acciones a probar:", len(tick), "· universos:", {k: len(v) for k, v in member.items()})

    frames = []
    for i in range(0, len(tick), 100):
        frames.append(yf.download(tick[i:i + 100] + ["SPY"], period="20y", interval="1d", auto_adjust=True,
                                  actions=True, group_by="ticker", threads=True, progress=False))
        time.sleep(1)
    lv = lambda d: set(d.columns.get_level_values(0))
    close = pd.concat([pd.DataFrame({s: d[s]["Close"] for s in tick + ["SPY"] if s in lv(d)}) for d in frames], axis=1)
    close = close.loc[:, ~close.columns.duplicated()]
    vol = pd.concat([pd.DataFrame({s: d[s]["Volume"] for s in tick if s in lv(d)}) for d in frames], axis=1)
    vol = vol.loc[:, ~vol.columns.duplicated()].reindex(close.index)
    splits = {}
    for d in frames:
        for s_ in tick:
            if s_ in lv(d) and "Stock Splits" in d[s_].columns:
                sp_ = d[s_]["Stock Splits"].fillna(0)
                ev = [(pd.Timestamp(k).tz_localize(None) if pd.Timestamp(k).tzinfo else pd.Timestamp(k), float(v)) for k, v in sp_[sp_ > 0].items() if float(v) != 1.0]
                if ev:
                    splits[s_] = ev
    print("Acciones con splits en 10 años:", len(splits))
    close = close.ffill(limit=3)
    tick = [t for t in tick if t in close.columns and t in vol.columns and close[t].notna().sum() > 300]
    sp = [s for s, _, _ in S.sp500()]
    mom_cols = [c for c in close.columns if c in set(sp)]
    mom_pct_all = ((close[mom_cols] / close[mom_cols].shift(126)) / (close[mom_cols] / close[mom_cols].shift(21)) - 1).rank(axis=1, pct=True)

    idx = close.index
    end = idx[-1]
    start = end - pd.DateOffset(years=YEARS)
    days = [i for i, d in enumerate(idx) if d >= start]
    print(f"Período: {idx[days[0]].date()} a {end.date()} · {len(days)} ruedas · {len(tick)} acciones con precios")

    sec_msg = None
    try:
        ciks = sec_ciks()
    except Exception as e:
        sec_msg = str(e)
        print("SEC no disponible:", e)
        ciks = {}
    fund, edates = {}, {}
    for n_t, t in enumerate(tick):
        if time.time() - T0 > TIME_BUDGET_FUND:
            print(f"  tope de tiempo para balances alcanzado en {n_t}/{len(tick)}: el resto sigue sin fundamentos")
            for t2 in tick[n_t:]:
                fund[t2], edates[t2] = None, np.array([], dtype="datetime64[ns]")
            break
        cik = ciks.get(t.upper()) or ciks.get(t.upper().replace("-", "."))
        fd, filed = fundamentals(t, cik, close[t], splits.get(t)) if cik else (None, [])
        fund[t] = None if fd is None else np.vstack([fd.eps.values, fd.pe.values, fd.pe_med5.values, fd.rev_g.values, fd.eps_g.values])
        edates[t] = np.array(earnings_dates(t, filed, cik), dtype="datetime64[ns]")
        if n_t % 50 == 0:
            print(f"  balances {n_t + 1}/{len(tick)}")
    sec_ok = sum(1 for t in tick if fund[t] is not None and np.isfinite(fund[t][1]).any())
    print(f"Balances de la SEC: {sec_ok} de {len(tick)} empresas" + (f" · {sec_msg}" if sec_msg else ""))

    spy = close["SPY"].values
    mkt = (close["SPY"] > close["SPY"].rolling(200).mean()).values      # filtro de mercado
    print(f"Días con el S&P arriba de su media de 200: {mkt[days].mean()*100:.0f}% del período")
    dates = idx.values
    jobs = []
    for t in tick:
        mom = mom_pct_all[t].values if t in mom_pct_all.columns else np.full(len(idx), np.nan)
        jobs.append((t, close[t].values, vol[t].values, spy, mom, days, dates, edates[t], fund[t], mkt, meta[t][1]))
    res = {}
    with ProcessPoolExecutor() as ex:
        for k, (t, r) in enumerate(ex.map(run_ticker, jobs, chunksize=4)):
            res[t] = r
            if k % 50 == 0:
                print(f"  señales {k + 1}/{len(tick)}")

    def pack(u):
        bk = {k: [] for k in KEYS + ("base",)}
        for t in member[u]:
            r = res.get(t)
            if not r:
                continue
            extra = {"t": t, "sector": meta[t][1]}
            for k in KEYS:
                bk[k] += [dict(e, **extra) for e in r["eps"][k]]
            bk["base"] += [dict(e, **extra) for e in r["base"]]
        bset = sorted({f"{r['t']}|{r['date']}" for r in bk["B"]})
        ex = []
        for t in member[u]:
            r = res.get(t)
            if r:
                ex += r.get("exits", [])
        exits = {}
        if ex:
            hold = np.array([x["hold"] for x in ex])
            exits["hold"] = {"label": "Mantener 12 meses sin vender", "n": len(ex), "avg": float(hold.mean()), "med": float(np.median(hold)),
                             "win": float((hold > 0).mean()), "p10": float(np.percentile(hold, 10)), "days": EXIT_H, "fired": 0.0}
            for k_, lbl in EXIT_RULES.items():
                rr = np.array([x[k_][0] for x in ex])
                dd = np.array([x[k_][1] if x[k_][1] is not None else EXIT_H for x in ex])
                fired = np.array([x[k_][1] is not None for x in ex])
                diff = rr[fired] - hold[fired]
                exits[k_] = {"label": lbl, "n": len(ex), "avg": float(rr.mean()), "med": float(np.median(rr)), "win": float((rr > 0).mean()),
                             "p10": float(np.percentile(rr, 10)), "days": float(dd.mean()), "fired": float(fired.mean()),
                             "right": float((diff > 0).mean()) if fired.any() else None,
                             "saved": float(diff[diff > 0].mean()) if (diff > 0).any() else None,
                             "cost": float(diff[diff <= 0].mean()) if (diff <= 0).any() else None}
        convs = {}
        for k in ("P", "Q"):
            xs = []
            for t in member[u]:
                r = res.get(t)
                if r:
                    xs += r.get("conv", {}).get(k, [])
            if not xs:
                continue
            cv = [x for x in xs if x["conv"]]
            nc = [x for x in xs if not x["conv"]]
            m6 = lambda L, key="6m": {"n": len([x for x in L if x.get(key) is not None]),
                                      **({} if not [x for x in L if x.get(key) is not None] else
                                         {"win": float(np.mean([x[key] > 0 for x in L if x.get(key) is not None])),
                                          "avg": float(np.mean([x[key] for x in L if x.get(key) is not None])),
                                          "p10": float(np.percentile([x[key] for x in L if x.get(key) is not None], 10))})}
            convs[k] = {"n": len(xs), "rate": len(cv) / len(xs),
                        "days": float(np.median([x["days"] for x in cv if "days" in x])) if cv else None,
                        "wait": float(np.mean([x["wait"] for x in cv if "wait" in x])) if cv else None,
                        "conv6": m6(cv), "noconv6": m6(nc), "late6": m6(cv, "c6m")}
        return {
            "label": UNI_LBL[u], "n": len(member[u]), "tickers": unis[u], "conv": convs,
            "variants": {k: {"label": VARIANTS[k], **summarize(bk[k])} for k in KEYS},
            "base": {"label": "Comprar cualquier día cualquiera de estas acciones (referencia)", **summarize(bk["base"])},
            "by_sector": {k: by(bk[k], "sector") for k in KEYS},
            "by_setup": {k: by(bk[k], "setup") for k in KEYS},
            "by_year": {k: by(bk[k], "year") for k in KEYS + ("base",)},
            "split": {k: split_stats(bk[k]) for k in KEYS + ("base",)},
            "episodes": sorted([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k not in ("b", "c", "d", "m", "g")}
                                for r in bk["A"]], key=lambda r: r["date"], reverse=True),
            "b_set": bset,
            "exits": exits,
        }

    # ---- matriz sector x estrategia: muestra amplia + control juntas, cada estrategia contra
    # "comprar cualquier día" en ese MISMO sector (así no se confunde la señal con que el sector anduvo mal)
    def matrix():
        pool = (member.get("broad") or set()) | (member.get("broad2") or set())
        if not pool:
            return None
        rows = {k: {} for k in KEYS + ("base",)}
        for t in pool:
            r = res.get(t)
            if not r:
                continue
            sec = meta[t][1] or "Otro"
            for k in KEYS:
                rows[k].setdefault(sec, []).extend(dict(e, t=t) for e in r["eps"][k])
            rows["base"].setdefault(sec, []).extend(r["base"])
        def m(L):
            x = [e for e in L if e.get("6m") is not None]
            if not x:
                return {"n": 0}
            v = np.array([e["6m"] for e in x])
            b = [e["6m"] - e["spy_6m"] for e in x if e.get("spy_6m") is not None]
            return {"n": len(x), "win": float((v > 0).mean()), "avg": float(v.mean()),
                    "beat": float((np.array(b) > 0).mean()) if b else None}
        outm = {}
        for sec, B_ in rows["base"].items():
            bd, bv = m([e for e in B_ if e["date"] < SPLIT]), m([e for e in B_ if e["date"] >= SPLIT])
            ent = {"base": {**m(B_), "nt": None, "d": bd, "v": bv}, "v": {}}
            ball = ent["base"]
            for k in KEYS:
                L = rows[k].get(sec, [])
                a = m(L)
                if not a["n"]:
                    ent["v"][k] = {"n": 0}
                    continue
                d, v = m([e for e in L if e["date"] < SPLIT]), m([e for e in L if e["date"] >= SPLIT])
                nt = len({e["t"] for e in L if e.get("6m") is not None})
                dd = d["avg"] - bd["avg"] if d["n"] and bd["n"] else None
                dv = v["avg"] - bv["avg"] if v["n"] and bv["n"] else None
                ok = bool(a["n"] >= 30 and nt >= 5 and dd is not None and dv is not None and d["n"] >= 10 and v["n"] >= 10
                          and dd > 0 and dv > 0 and a["avg"] > ball["avg"])
                ent["v"][k] = {**a, "nt": nt, "dwin": a["win"] - ball["win"], "davg": a["avg"] - ball["avg"],
                               "d_n": d["n"], "v_n": v["n"], "d_davg": dd, "v_davg": dv, "ok": ok}
            outm[sec] = ent
        return {"label": "Muestra amplia + muestra de control (" + str(len(pool)) + " acciones)", "sectors": outm}

    # ---- señales de agotamiento sobre todas las acciones de EE.UU. del monitor
    def xstats(L):
        o_ = {"n": len(L)}
        if not L:
            return o_
        for hk in XH:
            r = np.array([e["r" + hk] for e in L]); m = np.array([e["m" + hk] for e in L]); sp_ = np.array([e["s" + hk] for e in L])
            o_[hk] = {"fell": float((r < 0).mean()), "fell5": float((r <= -0.05).mean()), "fell10": float((r <= -0.10).mean()),
                      "avg": float(r.mean()), "med": float(np.median(r)), "avg_fall": float(r[r < 0].mean()) if (r < 0).any() else None,
                      "touch5": float((m <= -0.05).mean()), "touch10": float((m <= -0.10).mean()), "mdd": float(np.median(m)),
                      "under": float((r < sp_).mean())}
        return o_

    def alerts_out():
        us = [t for t in tick if (meta[t][2] or "EE.UU.") == "EE.UU." and res.get(t)]
        xb = [e for t in us for e in res[t].get("xbase", [])]
        sig_ = {}
        for k, lbl in ALERTS.items():
            L, nt = [], set()
            for t in us:
                ev = res[t].get("alerts", {}).get(k, [])
                L += ev
                if ev:
                    nt.add(t)
            st = xstats(L)
            st["nt"] = len(nt)
            st["d"] = xstats([e for e in L if e["date"] < SPLIT]).get("90d")
            st["v"] = xstats([e for e in L if e["date"] >= SPLIT]).get("90d")
            sig_[k] = {"label": lbl, **st}
        return {"label": f"Todas las acciones de EE.UU. del monitor ({len(us)})", "base": xstats(xb),
                "base_d": xstats([e for e in xb if e["date"] < SPLIT]).get("90d"),
                "base_v": xstats([e for e in xb if e["date"] >= SPLIT]).get("90d"), "signals": sig_}

    out = {
        "alerts": alerts_out(),
        "matrix": matrix(),
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "period": {"from": str(idx[days[0]].date()), "to": str(end.date())},
        "split_date": SPLIT, "goal": GOAL, "gap": GAP, "target": TARGET, "stop": STOP, "ts_days": TS_DAYS,
        "sec": {"ok": sec_ok, "total": len(tick), "error": sec_msg},
        "universes": {u: pack(u) for u in unis if member[u]},
    }
    with open("backtest.json", "w", encoding="utf-8") as f:
        json.dump(S.no_nan(out), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    # ---- por acción: para buscar una empresa puntual en la página de control
    wk = list(range(days[0], len(idx), 5))
    if wk[-1] != len(idx) - 1:
        wk.append(len(idx) - 1)
    per = {}
    r4 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 4)
    for t in tick:
        r = res.get(t)
        if not r:
            continue
        sig = [{k: (r4(v) if isinstance(v, float) else v) for k, v in e.items() if k != "year"} for e in r["eps"]["A"]]
        per[t] = {"n": meta[t][0], "s": meta[t][1], "f": fund[t] is not None,
                  "w": [r4(x) for x in close[t].values[wk]],
                  "sig": sig,
                  "base": {h: stats(r["base"], h) for h in ("6m", "12m")}}
    with open("backtest_tickers.json", "w", encoding="utf-8") as f:
        json.dump(S.no_nan({"dates": [str(idx[i].date()) for i in wk], "spy": [r4(x) for x in spy[wk]], "tickers": per}),
                  f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"Detalle por acción: {len(per)} empresas")

    print("\n================ TRACK RÉCORD ================")
    print(f"Balances de la SEC: {sec_ok} de {len(tick)}" + (f" · {sec_msg}" if sec_msg else ""))
    for u, U in out["universes"].items():
        print(f"\n##### {U['label']} ({U['n']} acciones)")
        for k in KEYS:
            v = U["variants"][k]
            s_ = v["6m"]
            if s_.get("n"):
                print(f"  {k} 6m: {s_['n']} señales · positivas {s_['win']*100:.0f}% · le ganó al S&P {s_.get('beat',0)*100:.0f}%"
                      f" · promedio {s_['avg']*100:+.1f}% · peor 10% {s_['p10']*100:+.1f}%")
        X = U.get("exits") or {}
        if X:
            print(f"  -- Reglas de venta sobre {X['hold']['n']} compras C (comparadas con mantener 12 meses):")
            for k_, v in X.items():
                print(f"     {k_:10s} promedio {v['avg']*100:+.1f}% · peor 10% {v['p10']*100:+.1f}% · se activó {v['fired']*100:.0f}%"
                      + (f" · acertó {v['right']*100:.0f}% de las veces" if v.get('right') is not None else ""))
        b = U["base"]["6m"]
        if b.get("n"):
            print(f"  Referencia 6m: positivas {b['win']*100:.0f}% · promedio {b['avg']*100:+.1f}% · peor 10% {b['p10']*100:+.1f}%")


if __name__ == "__main__":
    main()
