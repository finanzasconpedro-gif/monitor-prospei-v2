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
    "Y": "Vía 'barata contra su historia' solo en consumo discrecional, industrial y salud: U en esos tres sectores (propuesta de Comprar en partes)",
    "Z": "Motor por sector + vía barata: T, o Y en consumo discrecional, industrial y salud (propuesta de motor completo)",
    "DF": "Checklist de defensivas (salud, consumo básico, utilities): 5 o más de 7: beta < 0,8, volatilidad < 25%, a menos de 3% del máximo, P/E 30%+ sobre su historia, tendencia alcista, 0-15% sobre la media de 200, RSI > 70",
    "CR": "Checklist de crecimiento (tecnología, comunicaciones, industrial): 3 o más de 5: beta < 0,8, 30%+ debajo del máximo, volatilidad > 45%, P/E > 40, RSI < 35",
    "CI": "Checklist de cíclicas (energía, materiales, consumo discrecional): 2 o más de 4: beta < 0,8, volatilidad > 45%, 30%+ sobre la media de 200, 30%+ debajo del máximo",
    "ZX": "Motor completo propuesto: Z (motor por sector + vía barata) o cualquiera de los tres checklists por familia",
    "T2": "Comprar endurecido: señal del perfil del sector (T) en las últimas 4 semanas y además, ese día, cumple el checklist de su familia o está barata contra su historia (P/E 30%+ debajo de su mediana de 5 años)",
    "T4": "Comprar solo en los sectores fuertes: T en tecnología, industrial, consumo discrecional y energía",
    "CK50": "Checklist con tendencia a favor: cumple el checklist de crecimiento o cíclicas y además el precio ya está arriba de su media de 50 días (rebote en marcha)",
    "CK20": "Checklist con rebote corto: cumple el checklist de crecimiento o cíclicas y además el precio está arriba de su media de 20 días",
    "NT": "Motor sin Comprar pleno: todos los caminos de producción menos T (barata contra su historia, checklists y giro temprano)",
    "NTQ": "Motor solo con los caminos fuertes: barata contra su historia (Y) y checklists de crecimiento y cíclicas (CR, CI)",
    "PR2": "Motor de producción con el Comprar endurecido: T2 en lugar de T, más Y, CR, CI y giro temprano (Q)",
    "DQ0": "Defensivas de calidad, comprando cualquier día (referencia): consumo básico, salud o utilities con beta < 0,8, volatilidad < 25%, ganancia positiva en los últimos 5 a 10 años y ventas sin caer más de 5%",
    "DQ1": "Defensivas de calidad en sobreventa: RSI < 35 con el precio arriba de su media de 200 días o la media de 200 todavía subiendo",
    "DQ2": "Defensivas de calidad con bajón corto: caen 5% a 10% desde su máximo de 3 meses sin perder la media de 200 días",
    "DQ3": "Defensivas de calidad que tocan su media de 200 días (±2% en la última semana) y rebotan arriba de ella",
    "DQX": "Defensivas de calidad: cualquiera de las tres señales (DQ1, DQ2 o DQ3)",
    "PR3": "Motor nuevo propuesto (octubre 2026): Comprar endurecido (T2) más Comprar en partes por barata contra su historia (Y) y checklists de crecimiento y cíclicas (CR, CI), sin giro temprano",
    "PRD": "Motor anterior (hasta octubre de 2026): Comprar o Comprar en partes por cualquiera de sus caminos: perfil del sector (T), vía barata en consumo discrecional, industrial y salud (Y), crecimiento y cíclicas castigadas (CR, CI) y giro temprano con fundamentos en industrial, energía y consumo discrecional (Q)",
}
VARIANTS.pop("_", None)
KEYS = ("A", "B", "C", "D", "E", "F", "G", "H", "J", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "DF", "CR", "CI", "ZX", "PRD",
        "T2", "T4", "CK50", "CK20", "NT", "NTQ", "PR2", "PR3",
        "DQ0", "DQ1", "DQ2", "DQ3", "DQX")
NEW_K = ("T2", "T4", "CK50", "CK20", "NT", "NTQ", "PR2", "PR3", "DQ0", "DQ1", "DQ2", "DQ3", "DQX")
DQ_SECT = {"Consumo básico", "Salud", "Utilities"}   # defensivas de calidad (variantes DQ)   # variantes para revisar el Comprar pleno
T4_SECT = {"Tecnología", "Industrial", "Consumo discrecional", "Energía"}
PART_SECT = {"Industrial", "Energía", "Consumo discrecional"}   # sectores donde el motor permite "en partes" por giro temprano
PE_CHEAP, PE_DEEP = 0.70, 0.50   # P/E contra su mediana de 5 años para las variantes U-X
PE_SECT = {"Consumo discrecional", "Industrial", "Salud"}
# ---- cartera simulada: sigue las señales con posiciones iguales; la plata sin usar queda en el S&P 500
PF_SLOTS = 30          # hasta 30 posiciones de 1/30 del capital cada una
# cartera: nombre -> (etiqueta, meses que mantiene, señales). Las señales son una lista de "cupos": cada cupo tiene
# sus variantes (en orden de prioridad) y cuántos de los 30 lugares puede ocupar.
_MIX = [{"keys": ["CR", "CI", "Z"], "slots": 21}, {"keys": ["DF"], "slots": 9}]
_PRD = [{"keys": ["PRD"], "slots": 30}]
PF_KEYS = {"PRD": ("Motor de producción (PRD) · 12 meses", 252, _PRD),
           "PRD6": ("Motor de producción (PRD) · 6 meses", 126, _PRD),
           "MIX": ("Repartida: 70% crecimiento/cíclicas castigadas + motor, 30% defensivas firmes · 12 meses", 252, _MIX),
           "MIX6": ("Repartida 70/30 · 6 meses", 126, _MIX),
           "CC": ("Solo crecimiento y cíclicas castigadas (CR + CI) · 12 meses", 252, [{"keys": ["CR", "CI"], "slots": 30}]),
           "CC6": ("Solo CR + CI · 6 meses", 126, [{"keys": ["CR", "CI"], "slots": 30}]),
           "ZX": ("Motor + checklists sin repartir (ZX) · 12 meses", 252, [{"keys": ["ZX"], "slots": 30}]),
           "Z": ("Motor actual (Z) · 12 meses", 252, [{"keys": ["Z"], "slots": 30}]),
           "Z6": ("Motor actual (Z) · 6 meses", 126, [{"keys": ["Z"], "slots": 30}]),
           "NT": ("Motor sin Comprar pleno (NT) · 12 meses", 252, [{"keys": ["NT"], "slots": 30}]),
           "PR2": ("Motor con Comprar endurecido (PR2) · 12 meses", 252, [{"keys": ["PR2"], "slots": 30}]),
           "PR3": ("Motor nuevo propuesto (PR3) · 12 meses", 252, [{"keys": ["PR3"], "slots": 30}]),
           "PR36": ("Motor nuevo propuesto (PR3) · 6 meses", 126, [{"keys": ["PR3"], "slots": 30}]),
           "PR3D": ("Repartida: 70% motor nuevo + 30% defensivas de calidad con señal (DQX) · 12 meses", 252,
                    [{"keys": ["PR3"], "slots": 21}, {"keys": ["DQX"], "slots": 9}]),
           "PR3Q": ("Repartida: 70% motor nuevo + 30% defensivas de calidad cualquier día (DQ0) · 12 meses", 252,
                    [{"keys": ["PR3"], "slots": 21}, {"keys": ["DQ0"], "slots": 9}])}
# Checklists por familia (elegidos por el análisis de variables con las acciones de diseño): familia, condiciones, mínimo
CK = {"DF": ("Defensivas", ["beta_lo", "lowvol", "at_high", "pe_rich", "trend", "near200", "rsi_hi"], 5),
      "CR": ("Crecimiento", ["beta_lo", "dd_deep", "highvol", "pe_gt40", "rsi_lo"], 3),
      "CI": ("Cíclicas", ["beta_lo", "highvol", "ext30", "dd_deep"], 2)}
IND_MIN = 5            # empresas mínimas para comparar contra la industria; si no, contra el sector   # sectores donde la vía barata se sostuvo (Y, Z)
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
        # sin los papeles de seguimiento propio: las muestras son solo del S&P 500
        df = pd.DataFrame([{"t": r["t"], "sector": r["sector"], "region": r.get("region")} for r in rows if not r.get("extra")])
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
                           for r in rows if not r.get("extra")])
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
    bi = [r[key] - r["ind_" + key] for r in v if r.get("ind_" + key) is not None]
    if bi:
        out["beat_ind"] = float((np.array(bi) > 0).mean())
        out["alpha_ind"] = float(np.mean(bi))
        out["n_ind"] = len(bi)
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
        sig["Y"] = bool(u_ and sector in PE_SECT)
        sig["Z"] = bool(sig["T"] or sig["Y"])
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


# ======================================================================== modelo de probabilidad
# En vez de filtros de "sí o no", estima la probabilidad de que comprar hoy dé ganancia a 12 meses, combinando
# variables de la acción y del mercado. Se valida AÑO POR AÑO (para predecir un año solo se usa lo que ya se
# sabía antes) y con acciones que nunca se usaron para elegir reglas.
PM_H = 252            # horizonte: 12 meses
PM_STEP = 5           # una observación cada 5 ruedas por acción
PM_LAM = 10.0         # regularización (evita que el modelo exagere con una variable)
PM_THR = (0.85, 0.80, 0.75, 0.70, 0.65)
PM_BINS = (0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 1.01)
PM_FEAT_LBL = {
    "mom": "Momentum 6 meses sin el último (puesto en el mercado)", "r1m": "Rendimiento del último mes",
    "dist200": "Distancia a su media de 200 días", "dist200_2": "Distancia a la media de 200 (al cuadrado)",
    "above200": "Arriba de su media de 200", "gc": "Media de 50 arriba de la de 200", "slope200": "Pendiente de la media de 200",
    "rsi": "RSI 14 días", "rsi_2": "RSI (al cuadrado)", "dd52": "Caída desde el máximo de 52 semanas",
    "dd3": "Caída desde el máximo de 3 meses", "rebound": "Corrección de 5-20% con rebote (sobre la media de 20)",
    "vol": "Volatilidad de 3 meses", "pe_r": "P/E contra su mediana de 5 años", "pe_cheap": "P/E 30%+ debajo de su historia",
    "eps_pos": "Ganancia positiva", "rev_g": "Crecimiento de ventas", "eps_g": "Crecimiento de ganancias", "no_fund": "Sin datos de balances",
    "spy_dist200": "S&P 500: distancia a su media de 200", "spy_r6m": "S&P 500: rendimiento 6 meses", "spy_dd52": "S&P 500: caída desde su máximo",
    "br200": "Amplitud: % de acciones sobre su media de 200", "br50": "Amplitud: % de acciones sobre su media de 50",
    "vix": "VIX", "vix_rel": "VIX contra su mediana de 1 año", "tnx": "Tasa a 10 años", "tnx_ch": "Cambio de la tasa a 10 años en 6 meses",
}


def logit_fit(X, y, lam=PM_LAM, it=30):
    n, k = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    w = np.zeros(k + 1)
    R = lam * np.eye(k + 1)
    R[0, 0] = 0
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(Xb @ w, -30, 30)))
        W = p * (1 - p)
        H = Xb.T @ (Xb * W[:, None]) + R
        g = Xb.T @ (p - y) + R @ w
        st = np.linalg.solve(H, g)
        w -= st
        if np.abs(st).max() < 1e-7:
            break
    return w


def logit_pred(X, w):
    return 1 / (1 + np.exp(-np.clip(w[0] + X @ w[1:], -30, 30)))


def prob_model(close, fund, meta, us_t, design, valid, grp, mkx):
    """Arma la tabla (fecha x acción) de variables, entrena año por año y evalúa sobre las acciones de validación."""
    idx = close.index
    C = close[us_t]
    n = len(idx)
    spy = close["SPY"]
    # ---- variables de cada acción (vectorizadas)
    s20, s50, s200 = C.rolling(20).mean(), C.rolling(50).mean(), C.rolling(200).mean()
    mom_raw = (C / C.shift(126)) / (C / C.shift(21)) - 1
    F = {
        "mom": mom_raw.rank(axis=1, pct=True),
        "r1m": (C / C.shift(21) - 1).clip(-0.5, 0.5),
        "dist200": (C / s200 - 1).clip(-0.6, 1.0),
        "above200": (C > s200).astype(float).where(s200.notna()),
        "gc": (s50 > s200).astype(float).where(s200.notna()),
        "slope200": (s200 / s200.shift(21) - 1).clip(-0.2, 0.2),
    }
    d = C.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    F["rsi"] = (100 - 100 / (1 + up / dn.replace(0, np.nan))) / 100
    F["dd52"] = (C / C.rolling(252, min_periods=120).max() - 1).clip(-0.9, 0)
    dd3 = C / C.rolling(63, min_periods=40).max() - 1
    F["dd3"] = dd3.clip(-0.6, 0)
    F["rebound"] = ((dd3 <= -0.05) & (dd3 >= -0.20) & (C > s20)).astype(float)
    F["vol"] = (np.log(C).diff().rolling(63).std() * np.sqrt(252)).clip(0, 1.5)
    F["dist200_2"] = F["dist200"] ** 2
    F["rsi_2"] = (F["rsi"] - 0.5) ** 2
    # fundamentos de la SEC (tal como se conocían ese día)
    pe_r = pd.DataFrame(np.nan, index=idx, columns=us_t)
    eps_pos = pd.DataFrame(np.nan, index=idx, columns=us_t)
    rev_g = pd.DataFrame(np.nan, index=idx, columns=us_t)
    eps_g = pd.DataFrame(np.nan, index=idx, columns=us_t)
    for t in us_t:
        fd = fund.get(t)
        if fd is None:
            continue
        e, pe, med, rg, eg = fd
        with np.errstate(divide="ignore", invalid="ignore"):
            pe_r[t] = np.where((pe > 0) & (med > 0), pe / med, np.nan)
        eps_pos[t] = np.where(np.isfinite(e), (e > 0).astype(float), np.nan)
        rev_g[t] = rg
        eps_g[t] = eg
    F["pe_r"] = pe_r.clip(0.2, 3)
    F["pe_cheap"] = (pe_r <= 0.70).astype(float)
    F["eps_pos"] = eps_pos
    F["rev_g"] = rev_g.clip(-0.5, 1)
    F["eps_g"] = eps_g.clip(-1, 2)
    F["no_fund"] = eps_pos.isna().astype(float)
    # ---- variables del mercado (iguales para todas las acciones ese día)
    M = pd.DataFrame(index=idx)
    M["spy_dist200"] = (spy / spy.rolling(200).mean() - 1)
    M["spy_r6m"] = spy / spy.shift(126) - 1
    M["spy_dd52"] = spy / spy.rolling(252, min_periods=120).max() - 1
    M["br200"] = (C > s200).sum(axis=1) / s200.notna().sum(axis=1).replace(0, np.nan)
    M["br50"] = (C > s50).sum(axis=1) / s50.notna().sum(axis=1).replace(0, np.nan)
    if "^VIX" in mkx:
        v = mkx["^VIX"]
        M["vix"] = v
        M["vix_rel"] = v / v.rolling(252, min_periods=100).median()
    if "^TNX" in mkx:
        r_ = mkx["^TNX"]
        M["tnx"] = r_
        M["tnx_ch"] = r_ - r_.shift(126)
    secs = sorted({meta[t][1] or "Otro" for t in us_t})
    # ---- filas: cada 5 ruedas, con al menos 260 ruedas de historia
    rows_i = np.arange(260, n, PM_STEP)
    fwd = (C.shift(-PM_H) / C - 1).values
    spy_f = (spy.shift(-PM_H) / spy - 1).values
    # rendimiento de su industria (las demás empresas, igual peso) para comparar
    gcols = {}
    for j, t in enumerate(us_t):
        gcols.setdefault(grp.get(t, "?"), []).append(j)
    ind_f = np.full(fwd.shape, np.nan)
    for g, js in gcols.items():
        sub = fwd[:, js]
        sm, nn = np.nansum(sub, axis=1), np.isfinite(sub).sum(axis=1)
        for k_, j in enumerate(js):
            own = sub[:, k_]
            cnt = nn - np.isfinite(own)
            ind_f[:, j] = np.where(cnt >= 2, (sm - np.nan_to_num(own)) / np.maximum(cnt, 1), np.nan)
    fnames = list(F) + list(M.columns) + ["sec_" + x for x in secs[1:]]
    Fv = {k: v.values for k, v in F.items()}
    Mv = M.values
    blocks, meta_rows = [], []
    for j, t in enumerate(us_t):
        px = C[t].values
        ok = np.isfinite(px[rows_i]) & (np.arange(n)[rows_i] >= 0)
        ii = rows_i[ok]
        if not len(ii):
            continue
        cols = [Fv[k][ii, j] for k in F] + [Mv[ii, m] for m in range(Mv.shape[1])]
        sec = meta[t][1] or "Otro"
        cols += [np.full(len(ii), 1.0 if sec == x else 0.0) for x in secs[1:]]
        blocks.append(np.column_stack(cols).astype(np.float32))
        meta_rows.append(np.column_stack([np.full(len(ii), j), ii]))
    X = np.vstack(blocks)
    R_ = np.vstack(meta_rows).astype(int)
    tj, ti = R_[:, 0], R_[:, 1]
    y_ret = fwd[ti, tj]
    sp_ret = spy_f[ti]
    in_ret = ind_f[ti, tj]
    years = idx.year.values[ti]
    dates = idx.values[ti]
    is_d = np.array([us_t[j] in design for j in tj])
    is_v = np.array([us_t[j] in valid for j in tj])
    has_y = np.isfinite(y_ret)
    print(f"Modelo de probabilidad: {len(X)} observaciones, {X.shape[1]} variables")

    def prep(Xtr):
        mu = np.nanmean(Xtr, axis=0)
        sd = np.nanstd(Xtr, axis=0)
        sd[~np.isfinite(sd) | (sd < 1e-9)] = 1
        mu[~np.isfinite(mu)] = 0
        return mu, sd

    def z(Xa, mu, sd):
        Z = (Xa - mu) / sd
        Z[~np.isfinite(Z)] = 0
        return Z

    # ---- validación año por año: para el año Y se entrena con lo que tenía resultado conocido antes del 1/1/Y
    pred = np.full(len(X), np.nan)
    test_years = []
    yr_min = int(years.min()) + 3
    yr_max = int(years[has_y].max())
    for Y in range(yr_min, yr_max + 1):
        cut = np.datetime64(f"{Y - 1}-01-01")       # fecha de compra + 12 meses < 1/1/Y
        tr = is_d & has_y & (dates < cut)
        te = is_v & (years == Y)
        if tr.sum() < 5000 or not te.any():
            continue
        mu, sd = prep(X[tr])
        w = logit_fit(z(X[tr], mu, sd), (y_ret[tr] > 0).astype(float))
        pred[te] = logit_pred(z(X[te], mu, sd), w)
        test_years.append(Y)
    ev = is_v & has_y & np.isfinite(pred)

    def grp_stats(m):
        if not m.any():
            return {"n": 0}
        r, s_, i_ = y_ret[m], sp_ret[m], in_ret[m]
        oi = np.isfinite(i_)
        return {"n": int(m.sum()), "p": float(np.mean(pred[m])), "win": float((r > 0).mean()), "avg": float(r.mean()),
                "med": float(np.median(r)), "beat": float((r > s_).mean()), "alpha": float((r - s_).mean()),
                "beat_ind": float((r[oi] > i_[oi]).mean()) if oi.any() else None,
                "alpha_ind": float((r[oi] - i_[oi]).mean()) if oi.any() else None,
                "l20": float((r <= -0.20).mean())}

    calib = []
    for a, b in zip(PM_BINS[:-1], PM_BINS[1:]):
        st = grp_stats(ev & (pred >= a) & (pred < b))
        st.update(lo=a, hi=min(b, 1))
        calib.append(st)
    n_months = max(1, len({str(x)[:7] for x in dates[ev]}))
    n_val = len(valid)
    thr = []
    for th in PM_THR:
        m = ev & (pred >= th)
        st = grp_stats(m)
        # señales nuevas por mes: acción que cruza el umbral (no estaba arriba en la observación anterior)
        prev = np.zeros(len(X), dtype=bool)
        order = np.lexsort((ti, tj))
        mm = (pred >= th)[order]
        same = np.r_[False, tj[order][1:] == tj[order][:-1]]
        new_ = mm & ~(np.r_[False, mm[:-1]] & same)
        prev[order] = new_
        st.update(thr=th, share=float(m.sum() / max(ev.sum(), 1)),
                  new_pm=float((prev & ev).sum() / n_months), stocks=n_val)
        thr.append(st)
    by_year = []
    for Y in test_years:
        m = ev & (years == Y)
        if not m.any():
            continue
        o_ = {"y": str(Y), "all": grp_stats(m)}
        for th in (0.80, 0.75, 0.70):
            mt = m & (pred >= th)
            o_[f"t{int(th * 100)}"] = {**grp_stats(mt), "share": float(mt.sum() / m.sum())}
        by_year.append(o_)
    # ---- modelo final con todo lo que tiene resultado (para usar en el screener)
    tr = has_y
    mu, sd = prep(X[tr])
    w = logit_fit(z(X[tr], mu, sd), (y_ret[tr] > 0).astype(float))
    coefs = sorted([{"f": f, "lbl": PM_FEAT_LBL.get(f, f.replace("sec_", "Sector: ")), "w": float(c)} for f, c in zip(fnames, w[1:])],
                   key=lambda x: -abs(x["w"]))
    # probabilidad de hoy en las acciones de validación (lo que diría el modelo ahora)
    last_i = int(ti.max())
    now_m = ti == last_i
    p_now = logit_pred(z(X[now_m], mu, sd), w)
    now = sorted([{"t": us_t[j], "p": float(pv)} for j, pv in zip(tj[now_m], p_now)], key=lambda x: -x["p"])
    return {"label": "Probabilidad de ganar plata a 12 meses", "h": "12m", "test_years": [str(y) for y in test_years],
            "n_obs": int(ev.sum()), "stocks": n_val, "base": grp_stats(ev), "calib": calib, "thr": thr, "years": by_year,
            "coefs": coefs[:25], "now": now[:40], "now_date": str(idx[last_i].date()),
            "model": {"features": fnames, "mean": [float(x) for x in mu], "std": [float(x) for x in sd], "w": [float(x) for x in w],
                      "secs": secs, "horizon": PM_H}}


# ======================================================================== análisis de variables por familia
# ¿Qué condiciones aparecen más seguido en las buenas oportunidades? Buena oportunidad = a 12 meses ganó plata
# Y le ganó a lo que debía rendir según su riesgo (beta x lo que hizo el S&P 500). Así una defensiva que sube
# menos que el índice pero más de lo que le corresponde cuenta como acierto, y una tecnológica que solo subió
# con el mercado no. Las condiciones se eligen con las acciones de diseño y se prueban con las de validación.
VA_FAM = {"Tecnología": "Crecimiento", "Comunicaciones": "Crecimiento", "Industrial": "Crecimiento",
          "Energía": "Cíclicas", "Materiales": "Cíclicas", "Consumo discrecional": "Cíclicas",
          "Salud": "Defensivas", "Consumo básico": "Defensivas", "Utilities": "Defensivas", "Servicios públicos": "Defensivas",
          "Financiero": "Financieras", "Real estate": "Financieras", "Inmobiliario": "Financieras"}
VA_K = 8              # condiciones del checklist de cada familia
VA_MIN_LIFT = 0.02    # una condición entra si sube la chance de buena oportunidad al menos 2 puntos
VA_HALF = "2017-01-01"
VA_LBL = {
    "trend": ("Técnica", "Tendencia alcista (arriba de la media de 200 y la de 50 sobre la de 200)"),
    "slope": ("Técnica", "Media de 200 subiendo"),
    "near200": ("Técnica", "Entre 0% y 15% arriba de su media de 200 (no estirada)"),
    "ext30": ("Técnica", "Más de 30% arriba de su media de 200 (estirada)"),
    "below200": ("Técnica", "Debajo de su media de 200"),
    "mom_hi": ("Técnica", "Momentum: entre el 30% más fuerte del mercado (6 meses sin el último)"),
    "mom_lo": ("Técnica", "Momentum: entre el 30% más débil del mercado"),
    "mom_sec": ("Técnica", "Momentum: entre el 30% más fuerte de su sector"),
    "rs3": ("Técnica", "Le ganó al S&P 500 en los últimos 3 meses"),
    "rsi_mid": ("Técnica", "RSI entre 40 y 60"),
    "rsi_lo": ("Técnica", "RSI menor a 35 (sobrevendida)"),
    "rsi_hi": ("Técnica", "RSI mayor a 70 (sobrecomprada)"),
    "rebound": ("Técnica", "Corrección de 5% a 20% con rebote (sobre su media de 20)"),
    "dd_mid": ("Técnica", "Entre 10% y 30% debajo de su máximo de 52 semanas"),
    "dd_deep": ("Técnica", "Más de 30% debajo de su máximo de 52 semanas"),
    "at_high": ("Técnica", "A menos de 3% de su máximo de 52 semanas"),
    "fell1m": ("Técnica", "Cayó más de 5% en el último mes"),
    "lowvol": ("Riesgo", "Volatilidad menor a 25% anual"),
    "highvol": ("Riesgo", "Volatilidad mayor a 45% anual"),
    "beta_lo": ("Riesgo", "Beta menor a 0,8"),
    "beta_hi": ("Riesgo", "Beta mayor a 1,3"),
    "eps_pos": ("Fundamental", "Ganancia de 12 meses positiva"),
    "rev_up": ("Fundamental", "Ventas creciendo contra el año anterior"),
    "rev_10": ("Fundamental", "Ventas creciendo más de 10%"),
    "eps_up": ("Fundamental", "Ganancias creciendo contra el año anterior"),
    "eps_15": ("Fundamental", "Ganancias creciendo más de 15%"),
    "pe_cheap": ("Valuación", "P/E 30% o más debajo de su mediana de 5 años"),
    "pe_below": ("Valuación", "P/E debajo de su mediana de 5 años"),
    "pe_rich": ("Valuación", "P/E 30% o más arriba de su mediana de 5 años"),
    "pe_lt15": ("Valuación", "P/E menor a 15"),
    "pe_gt40": ("Valuación", "P/E mayor a 40"),
    "mkt_up": ("Mercado", "S&P 500 arriba de su media de 200"),
    "breadth": ("Mercado", "Más de la mitad de las acciones arriba de su media de 200"),
    "vix_hi": ("Mercado", "VIX mayor a 25 (miedo en el mercado)"),
}


def va_frames(close, fund, meta, us_t, mkx):
    """Condiciones de sí o no (fecha x acción) que usan el análisis de variables y los checklists."""
    idx = close.index
    n = len(idx)
    C = close[us_t]
    spy = close["SPY"]
    m_ = len(us_t)
    sec = [meta[t][1] or "Otro" for t in us_t]
    fam = np.array([VA_FAM.get(x, "Otras") for x in sec])
    s20, s50, s200 = C.rolling(20).mean(), C.rolling(50).mean(), C.rolling(200).mean()
    mom_raw = (C / C.shift(126)) / (C / C.shift(21)) - 1
    mom = mom_raw.rank(axis=1, pct=True)
    mom_s = pd.DataFrame(np.nan, index=idx, columns=us_t)
    for sname in set(sec):
        cols = [t for t, x in zip(us_t, sec) if x == sname]
        mom_s[cols] = mom_raw[cols].rank(axis=1, pct=True)
    d = C.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    dd52 = C / C.rolling(252, min_periods=120).max() - 1
    dd3 = C / C.rolling(63, min_periods=40).max() - 1
    vol = np.log(C).diff().rolling(63).std() * np.sqrt(252)
    dist = C / s200 - 1
    # beta de 5 años con rendimientos mensuales (la misma medida que la ficha del monitor), conocida a fin de cada mes
    Cm, sm = C.resample("ME").last().pct_change(), spy.resample("ME").last().pct_change()
    mean_xy = Cm.mul(sm, axis=0).rolling(60, min_periods=36).mean()
    beta_m = (mean_xy - Cm.rolling(60, min_periods=36).mean().mul(sm.rolling(60, min_periods=36).mean(), axis=0)).div(
        sm.rolling(60, min_periods=36).var(ddof=0), axis=0)
    beta = beta_m.reindex(idx, method="ffill")
    pe = pd.DataFrame(np.nan, index=idx, columns=us_t)
    pe_r = pd.DataFrame(np.nan, index=idx, columns=us_t)
    eps = pd.DataFrame(np.nan, index=idx, columns=us_t)
    rev_g = pd.DataFrame(np.nan, index=idx, columns=us_t)
    eps_g = pd.DataFrame(np.nan, index=idx, columns=us_t)
    for t in us_t:
        fd = fund.get(t)
        if fd is None:
            continue
        e, pe_, med, rg, eg = fd
        eps[t], pe[t], rev_g[t], eps_g[t] = e, pe_, rg, eg
        with np.errstate(divide="ignore", invalid="ignore"):
            pe_r[t] = np.where((pe_ > 0) & (med > 0), pe_ / med, np.nan)
    spy200 = spy / spy.rolling(200).mean() - 1
    br = (C > s200).sum(axis=1) / s200.notna().sum(axis=1).replace(0, np.nan)
    vix = mkx["^VIX"] if "^VIX" in mkx else pd.Series(np.nan, index=idx)
    r3 = C / C.shift(63) - 1
    spy3 = spy / spy.shift(63) - 1
    bc = lambda s_: np.broadcast_to(s_.values[:, None], (n, m_))
    K = {
        "trend": (C > s200) & (s50 > s200), "slope": s200 > s200.shift(21), "near200": (dist >= 0) & (dist <= 0.15),
        "ext30": dist > 0.30, "below200": C < s200, "mom_hi": mom >= 0.70, "mom_lo": mom <= 0.30, "mom_sec": mom_s >= 0.70,
        "rs3": r3.gt(spy3, axis=0), "rsi_mid": (rsi >= 40) & (rsi <= 60), "rsi_lo": rsi < 35, "rsi_hi": rsi > 70,
        "rebound": (dd3 <= -0.05) & (dd3 >= -0.20) & (C > s20), "dd_mid": (dd52 <= -0.10) & (dd52 >= -0.30),
        "dd_deep": dd52 < -0.30, "at_high": dd52 > -0.03, "fell1m": (C / C.shift(21) - 1) < -0.05,
        "lowvol": vol < 0.25, "highvol": vol > 0.45, "beta_lo": beta < 0.8, "beta_hi": beta > 1.3,
        "eps_pos": eps > 0, "rev_up": rev_g > 0, "rev_10": rev_g > 0.10, "eps_up": eps_g > 0, "eps_15": eps_g > 0.15,
        "pe_cheap": pe_r <= 0.70, "pe_below": pe_r < 1.0, "pe_rich": pe_r >= 1.30,
        "pe_lt15": (pe > 0) & (pe < 15), "pe_gt40": pe > 40,
        "mkt_up": bc(spy200 > 0), "breadth": bc(br > 0.5), "vix_hi": bc(vix > 25),
    }
    return K, sec, fam, beta


def var_analysis(close, fund, meta, us_t, design, valid, mkx, KF=None):
    idx = close.index
    n = len(idx)
    C = close[us_t]
    spy = close["SPY"]
    m_ = len(us_t)
    K, sec, fam, beta = KF or va_frames(close, fund, meta, us_t, mkx)
    sec = list(sec)
    fam = np.array(fam)
    keys = list(K)
    # ---- filas: cada 5 ruedas por acción, con resultado a 12 meses conocido
    rows_i = np.arange(260, n - PM_H, PM_STEP)
    R = len(rows_i)
    ti, tj = np.tile(rows_i, m_), np.repeat(np.arange(m_), R)
    y = (C.shift(-PM_H) / C - 1).values[rows_i].ravel(order="F")
    sp_y = (spy.shift(-PM_H) / spy - 1).values[rows_i]
    sp_y = np.tile(sp_y, m_)
    b = beta.values[rows_i].ravel(order="F")
    b = np.where(np.isfinite(b), b, 1.0)
    ok = np.isfinite(y) & np.isfinite(sp_y)
    good = (y > 0) & (y > b * sp_y)
    Xc = np.zeros((len(y), len(keys)), dtype=bool)
    for k_, k in enumerate(keys):
        v = K[k]
        v = v.values if hasattr(v, "values") else np.asarray(v)
        Xc[:, k_] = np.asarray(v[rows_i], dtype=bool).ravel(order="F")
    dates = idx.values[ti]
    half1 = dates < np.datetime64(VA_HALF)
    tnames = np.array(us_t)
    is_d = np.isin(tnames, list(design))[tj]
    is_v = np.isin(tnames, list(valid))[tj]
    famr = fam[tj]
    print(f"Análisis de variables: {ok.sum()} observaciones con resultado, {len(keys)} condiciones")

    def lift_of(m, k_):
        c = Xc[m, k_]
        g = good[m]
        if c.sum() < 200 or (~c).sum() < 200:
            return None, None, None
        return float(g[c].mean() - g.mean()), float(g[c].mean()), float(g[~c].mean())

    out_f = {}
    for fname in ["Todas", "Crecimiento", "Cíclicas", "Defensivas", "Financieras"]:
        fm = ok if fname == "Todas" else ok & (famr == fname)
        md, mv = fm & is_d, fm & is_v
        if md.sum() < 2000 or mv.sum() < 1000:
            continue
        p0d = float(good[md].mean())
        conds = []
        for k_, k in enumerate(keys):
            ld, py, pn = lift_of(md, k_)
            if ld is None:
                continue
            lv, _, _ = lift_of(mv, k_)
            l1, _, _ = lift_of(md & half1, k_)
            l2, _, _ = lift_of(md & ~half1, k_)
            c = Xc[md, k_]
            g = good[md]
            same = lambda a: a is not None and np.sign(a) == np.sign(ld) and abs(a) >= 0.01
            conds.append({"k": k, "grp": VA_LBL[k][0], "lbl": VA_LBL[k][1], "freq": float(c.mean()),
                          "in_good": float(c[g].mean()), "in_bad": float(c[~g].mean()), "p_yes": py, "p_no": pn,
                          "lift": ld, "lift_v": lv, "lift_h1": l1, "lift_h2": l2,
                          "robust": bool(abs(ld) >= VA_MIN_LIFT and same(l1) and same(l2) and same(lv))})
        conds.sort(key=lambda x: -x["lift"])
        # ---- checklist: las condiciones que más suben la chance EN DISEÑO (estables en las dos mitades), sin repetir
        pick = []
        for c in conds:
            if len(pick) >= VA_K:
                break
            if c["lift"] < VA_MIN_LIFT or not (c["lift_h1"] or 0) > 0.005 or not (c["lift_h2"] or 0) > 0.005:
                continue
            if c["grp"] == "Mercado":
                continue        # el mercado no elige acciones: es igual para todas ese día
            if not 0.05 <= c["freq"] <= 0.95:
                continue
            k_ = keys.index(c["k"])
            if any(abs(np.corrcoef(Xc[md, k_], Xc[md, keys.index(p)])[0, 1]) > 0.6 for p in pick):
                continue
            pick.append(c["k"])
        ck = []
        if pick:
            cols = [keys.index(p) for p in pick]
            score = Xc[:, cols].sum(axis=1)
            for samp, mm in (("design", md), ("valid", mv)):
                n_months = max(1, len({str(x)[:7] for x in dates[mm]}))
                n_st = len(set(tj[mm]))
                rows_ = []
                for th in range(len(pick), 0, -1):
                    q = mm & (score >= th)
                    if not q.any():
                        rows_.append({"n_of": th, "n": 0})
                        continue
                    # señales nuevas por mes: la acción pasa a cumplir th o más (no cumplía en la observación anterior)
                    qq = score >= th
                    prev_same = np.r_[False, tj[1:] == tj[:-1]]
                    new_ = qq & ~(np.r_[False, qq[:-1]] & prev_same)
                    rows_.append({"n_of": th, "n": int(q.sum()), "share": float(q.sum() / mm.sum()),
                                  "good": float(good[q].mean()), "win": float((y[q] > 0).mean()), "avg": float(y[q].mean()),
                                  "alpha_b": float((y[q] - b[q] * sp_y[q]).mean()), "l20": float((y[q] <= -0.20).mean()),
                                  "pm": float((new_ & mm).sum() / n_months), "stocks": n_st,
                                  "good_h1": float(good[q & half1].mean()) if (q & half1).any() else None,
                                  "good_h2": float(good[q & ~half1].mean()) if (q & ~half1).any() else None})
                base_ = {"n": int(mm.sum()), "good": float(good[mm].mean()), "win": float((y[mm] > 0).mean()),
                         "avg": float(y[mm].mean()), "alpha_b": float((y[mm] - b[mm] * sp_y[mm]).mean()),
                         "l20": float((y[mm] <= -0.20).mean()),
                         "good_h1": float(good[mm & half1].mean()), "good_h2": float(good[mm & ~half1].mean())}
                ck.append({"sample": samp, "base": base_, "rows": rows_})
        out_f[fname] = {"n": int(md.sum()), "n_v": int(mv.sum()), "p0": p0d, "p0_v": float(good[mv].mean()),
                        "sectors": sorted({x for x, f_ in zip(sec, fam) if fname == "Todas" or f_ == fname}),
                        "conds": conds, "pick": pick, "pick_lbl": [VA_LBL[p][1] for p in pick], "check": ck}
    return {"label": "Buena oportunidad = a 12 meses ganó plata y le ganó a lo que debía rendir según su riesgo (beta × S&P 500)",
            "from": str(idx[rows_i[0]].date()), "to": str(idx[rows_i[-1]].date()), "half": VA_HALF, "k": VA_K,
            "families": out_f}


def industries():
    try:
        rows = json.load(open("data.json", encoding="utf-8"))["rows"]
        return {r["t"]: r.get("industry") or "" for r in rows}
    except Exception:
        return {}


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

    try:
        mkx = yf.download(["^VIX", "^TNX"], period="20y", interval="1d", auto_adjust=True, progress=False)["Close"]
        mkx = mkx.reindex(close.index).ffill()
    except Exception as e:
        print("Sin VIX / tasa:", e)
        mkx = pd.DataFrame(index=close.index)
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

    # ---- contra su propia industria: rendimiento promedio (igual peso) de las DEMÁS empresas de su industria
    # en el mismo plazo (desde el cierre de compra). Industria con 5+ empresas en la prueba; si no, su sector.
    pos = {str(d)[:10]: i for i, d in enumerate(idx)}
    ind_map = industries()
    us_t = [t for t in tick if (meta[t][2] or "EE.UU.") == "EE.UU." and res.get(t)]
    n_ind = {}
    for t in us_t:
        n_ind[ind_map.get(t, "")] = n_ind.get(ind_map.get(t, ""), 0) + 1
    grp = {t: ("I:" + ind_map[t]) if ind_map.get(t) and n_ind[ind_map[t]] >= IND_MIN else "S:" + (meta[t][1] or "Otro") for t in us_t}
    # ---- checklists por familia como señales de compra (misma mecánica que las variantes: compra al cierre
    # siguiente, una señal cada 20 ruedas por acción) + ZX = Z o cualquier checklist
    try:
        # señales del motor para TODAS las acciones (también ADRs argentinos y brasileños, para el detalle por acción);
        # las estadísticas por muestra solo usan las del S&P 500, así que no cambian
        mt = [t for t in tick if res.get(t) and t in close.columns]
        KF = va_frames(close, fund, meta, us_t, mkx)          # para el análisis de variables (solo EE.UU.)
        KFm = va_frames(close, fund, meta, mt, mkx)
        Kc, sec_c, fam_c = KFm[0], KFm[1], KFm[2]
        famj = {t: f_ for t, f_ in zip(mt, fam_c)}
        Cv = close[mt].values
        spv = close["SPY"].values
        cnt = {k: np.zeros(Cv.shape) for k in CK}
        for k, (fname, conds, _) in CK.items():
            for cnd in conds:
                v = Kc[cnd]
                v = v.values if hasattr(v, "values") else np.asarray(v)
                cnt[k] += np.asarray(v, dtype=float)
        dset = set(days)
        n_ = len(idx)
        for j, t in enumerate(mt):
            c_ = Cv[:, j]
            sig_days = {}
            for k, (fname, conds, mn) in CK.items():
                if famj[t] != fname:
                    continue
                hit = cnt[k][:, j] >= mn
                sig_days[k] = hit
            z_days = {pos.get(e["date"]) for e in res[t]["eps"].get("Z", [])}
            for k in list(CK) + ["ZX"]:
                res[t]["eps"].setdefault(k, [])
                res[t]["eps"][k] = []
                last = -999
                for i in days:
                    if i + 1 >= n_ or not np.isfinite(c_[i + 1]):
                        continue
                    if k == "ZX":
                        on = (i in z_days) or any(bool(h[i]) for h in sig_days.values())
                    else:
                        on = k in sig_days and bool(sig_days[k][i])
                    if not on:
                        continue
                    if i - last > GAP:
                        p0 = c_[i + 1]
                        e = {"date": str(idx[i].date()), "setup": "Checklist " + (CK[k][0] if k in CK else "o motor"),
                             "at": int(sum(cnt[q][i, j] for q in sig_days) * 10) if sig_days else 0, "p": round(float(p0), 2),
                             "year": str(idx[i].year)}
                        for h, hn in H.items():
                            if i + 1 + hn < n_ and np.isfinite(c_[i + 1 + hn]):
                                e[h] = float(c_[i + 1 + hn] / p0 - 1)
                                e["spy_" + h] = float(spv[i + 1 + hn] / spv[i + 1] - 1)
                        path = c_[i + 2:i + 2 + TS_DAYS] / p0 - 1
                        ht = int(np.argmax(path >= TARGET)) if (path >= TARGET).any() else None
                        hs = int(np.argmax(path <= STOP)) if (path <= STOP).any() else None
                        if ht is not None and (hs is None or ht < hs):
                            e["ts"] = "objetivo"
                        elif hs is not None:
                            e["ts"] = "stop"
                        elif len(path) >= TS_DAYS:
                            e["ts"] = "abierta"
                        res[t]["eps"][k].append(e)
                    last = i
        # ---- motor de producción: unión de los caminos de compra del screener de hoy
        def emit(j, t, on_days, setup):
            """Episodios de compra a partir de los días con señal (misma mecánica: compra al cierre siguiente,
            una señal cada 20 ruedas por acción)."""
            c_ = Cv[:, j]
            out_ = []
            last = -999
            for i in on_days:
                if i + 1 >= n_ or not np.isfinite(c_[i + 1]) or i - last <= GAP:
                    if i - last <= GAP:
                        last = i
                    continue
                p0 = c_[i + 1]
                e = {"date": str(idx[i].date()), "setup": setup, "at": 0, "p": round(float(p0), 2), "year": str(idx[i].year)}
                for h, hn in H.items():
                    if i + 1 + hn < n_ and np.isfinite(c_[i + 1 + hn]):
                        e[h] = float(c_[i + 1 + hn] / p0 - 1)
                        e["spy_" + h] = float(spv[i + 1 + hn] / spv[i + 1] - 1)
                path = c_[i + 2:i + 2 + TS_DAYS] / p0 - 1
                ht = int(np.argmax(path >= TARGET)) if (path >= TARGET).any() else None
                hs = int(np.argmax(path <= STOP)) if (path <= STOP).any() else None
                if ht is not None and (hs is None or ht < hs):
                    e["ts"] = "objetivo"
                elif hs is not None:
                    e["ts"] = "stop"
                elif len(path) >= TS_DAYS:
                    e["ts"] = "abierta"
                out_.append(e)
                last = i
            return out_

        def ep_days(t, srcs):
            return sorted({pos.get(e["date"]) for k in srcs for e in res[t]["eps"].get(k, []) if pos.get(e["date"]) is not None})

        # ---- variantes para revisar el Comprar pleno (T)
        try:
            Cdf = close[mt]
            ab50 = (Cdf > Cdf.rolling(50).mean()).values
            ab20 = (Cdf > Cdf.rolling(20).mean()).values
            cheap = Kc["pe_cheap"]
            cheap = np.asarray(cheap.values if hasattr(cheap, "values") else cheap, dtype=bool)
            fam_ck = {fname: k for k, (fname, _, _) in CK.items()}
            dset_ = set(days)
            for j, t in enumerate(mt):
                sec_t = meta[t][1] or ""
                fk = fam_ck.get(famj[t])
                ck_hit = (cnt[fk][:, j] >= CK[fk][2]) if fk else np.zeros(n_, dtype=bool)
                cc_hit = ck_hit if fk in ("CR", "CI") else np.zeros(n_, dtype=bool)
                # T reciente: hubo señal del perfil del sector en las últimas 20 ruedas
                t_rec = np.zeros(n_, dtype=bool)
                for i0 in ep_days(t, ["T"]):
                    t_rec[i0:i0 + GAP + 1] = True
                t2 = sorted(i for i in days if t_rec[i] and (ck_hit[i] or cheap[i, j]))
                res[t]["eps"]["T2"] = emit(j, t, t2, "Comprar endurecido")
                res[t]["eps"]["T4"] = [dict(e) for e in res[t]["eps"].get("T", [])] if sec_t in T4_SECT else []
                res[t]["eps"]["CK50"] = emit(j, t, [i for i in days if cc_hit[i] and ab50[i, j]], "Checklist + media de 50")
                res[t]["eps"]["CK20"] = emit(j, t, [i for i in days if cc_hit[i] and ab20[i, j]], "Checklist + media de 20")
                q_ = ["Q"] if sec_t in PART_SECT else []
                res[t]["eps"]["NT"] = emit(j, t, ep_days(t, ["Y", "CR", "CI"] + q_), "Motor sin Comprar pleno")
                res[t]["eps"]["NTQ"] = emit(j, t, ep_days(t, ["Y", "CR", "CI"]), "Caminos fuertes")
                res[t]["eps"]["PR2"] = emit(j, t, ep_days(t, ["T2", "Y", "CR", "CI"] + q_), "Motor con Comprar endurecido")
                res[t]["eps"]["PR3"] = emit(j, t, ep_days(t, ["T2", "Y", "CR", "CI"]), "Motor nuevo")
            # ---- defensivas de calidad (tipo KO, PG, JNJ): filtro de calidad + tres formas de entrar en un bajón
            s200 = Cdf.rolling(200).mean()
            up200 = (Cdf > s200).values
            slope200 = (s200 > s200.shift(21)).values
            d_ = Cdf.diff()
            g_ = d_.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
            l_ = (-d_.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
            rsi_ = (100 - 100 / (1 + g_ / l_.replace(0, np.nan))).values
            dd3_ = (Cdf / Cdf.rolling(63, min_periods=40).max() - 1).values
            touch = ((Cdf.rolling(5).min() / s200) <= 1.02).values & up200 & (Cdf > Cdf.shift(3)).values
            vol_ = (np.log(Cdf).diff().rolling(63).std() * np.sqrt(252)).values
            beta_lo = np.asarray(Kc["beta_lo"].values if hasattr(Kc["beta_lo"], "values") else Kc["beta_lo"], dtype=bool)
            for j, t in enumerate(mt):
                if (meta[t][1] or "") not in DQ_SECT or fund.get(t) is None:
                    for k_ in ("DQ0", "DQ1", "DQ2", "DQ3", "DQX"):
                        res[t]["eps"][k_] = []
                    continue
                e_ = pd.Series(fund[t][0], index=idx)
                rg_ = fund[t][3]
                eps_ok = (e_.rolling(2520, min_periods=1260).min() > 0).values
                qual = beta_lo[:, j] & (vol_[:, j] < 0.25) & eps_ok & ~(rg_ < -0.05)
                d1 = qual & (rsi_[:, j] < 35) & (up200[:, j] | slope200[:, j])
                d2 = qual & (dd3_[:, j] <= -0.05) & (dd3_[:, j] >= -0.10) & up200[:, j]
                d3 = qual & touch[:, j]
                res[t]["eps"]["DQ0"] = emit(j, t, [i for i in days if qual[i]], "Defensiva de calidad")
                res[t]["eps"]["DQ1"] = emit(j, t, [i for i in days if d1[i]], "Defensiva en sobreventa")
                res[t]["eps"]["DQ2"] = emit(j, t, [i for i in days if d2[i]], "Defensiva con bajón corto")
                res[t]["eps"]["DQ3"] = emit(j, t, [i for i in days if d3[i]], "Defensiva en su media de 200")
                res[t]["eps"]["DQX"] = emit(j, t, [i for i in days if d1[i] or d2[i] or d3[i]], "Defensiva conservadora")
                for e in res[t]["eps"]["DQX"]:
                    i0 = pos.get(e["date"])
                    if i0 is not None:
                        e["setup"] = ("Sobreventa en tendencia" if d1[i0] else "Bajón corto" if d2[i0] else "Toca su media de 200")
        except Exception:
            import traceback
            traceback.print_exc()

        for j, t in enumerate(mt):
            c_ = Cv[:, j]
            srcs = ["T", "Y", "CR", "CI"] + (["Q"] if (meta[t][1] or "") in PART_SECT else [])
            on_days = sorted({pos.get(e["date"]) for k in srcs for e in res[t]["eps"].get(k, []) if pos.get(e["date"]) is not None})
            res[t]["eps"]["PRD"] = []
            last = -999
            for i in on_days:
                if i + 1 >= n_ or not np.isfinite(c_[i + 1]) or i - last <= GAP:
                    if i - last <= GAP:
                        last = i
                    continue
                p0 = c_[i + 1]
                e = {"date": str(idx[i].date()), "setup": "Motor de producción", "at": 0, "p": round(float(p0), 2), "year": str(idx[i].year)}
                for h, hn in H.items():
                    if i + 1 + hn < n_ and np.isfinite(c_[i + 1 + hn]):
                        e[h] = float(c_[i + 1 + hn] / p0 - 1)
                        e["spy_" + h] = float(spv[i + 1 + hn] / spv[i + 1] - 1)
                path = c_[i + 2:i + 2 + TS_DAYS] / p0 - 1
                ht = int(np.argmax(path >= TARGET)) if (path >= TARGET).any() else None
                hs = int(np.argmax(path <= STOP)) if (path <= STOP).any() else None
                if ht is not None and (hs is None or ht < hs):
                    e["ts"] = "objetivo"
                elif hs is not None:
                    e["ts"] = "stop"
                elif len(path) >= TS_DAYS:
                    e["ts"] = "abierta"
                res[t]["eps"]["PRD"].append(e)
                last = i
        print("Checklists y producción:", {k: sum(len(res[t]["eps"].get(k, [])) for t in mt) for k in list(CK) + ["ZX", "PRD"] + list(NEW_K)})
    except Exception as e_:
        import traceback
        traceback.print_exc()
        KF = None
        for t in tick:
            if res.get(t):
                for k in list(CK) + ["ZX"]:
                    res[t]["eps"].setdefault(k, [])
    for t in tick:
        if res.get(t):
            for k in KEYS:
                res[t]["eps"].setdefault(k, [])
    cl = close[us_t]
    gcols = {}
    for j, t in enumerate(us_t):
        gcols.setdefault(grp[t], []).append(j)
    for h, hn in H.items():
        fv = (cl.shift(-hn) / cl - 1).values
        gs = {g: (np.nansum(fv[:, js], axis=1), np.isfinite(fv[:, js]).sum(axis=1)) for g, js in gcols.items()}
        for j, t in enumerate(us_t):
            sm, nn = gs[grp[t]]
            r_ = res[t]
            for e in [x for L in r_["eps"].values() for x in L] + r_["base"]:
                i = pos.get(e["date"])
                if i is None or i + 1 >= len(idx):
                    continue
                own = fv[i + 1, j]
                k_ = nn[i + 1] - (1 if np.isfinite(own) else 0)
                if k_ >= 2:
                    e["ind_" + h] = float((sm[i + 1] - (own if np.isfinite(own) else 0)) / k_)

    # ---- cartera simulada siguiendo las señales
    def portfolio(univ, buckets, hold, slots=PF_SLOTS):
        names = [t for t in us_t if t in univ]
        if not names:
            return None
        if isinstance(buckets, str):
            buckets = [{"keys": [buckets], "slots": slots}]
        C = close[names].values
        col = {t: j for j, t in enumerate(names)}
        spx = close["SPY"].values
        sigs = {}
        for b_i, bk_ in enumerate(buckets):
            for prio, key in enumerate(bk_["keys"]):
                for t in names:
                    for e in res[t]["eps"].get(key, []):
                        i = pos.get(e["date"])
                        if i is not None:
                            # orden: primero la variante de más prioridad, después el puntaje técnico
                            sigs.setdefault(i + 1, []).append((-prio, e.get("at", 0) or 0, t, b_i))
        cap = [bk_["slots"] for bk_ in buckets]
        own = {}
        d0, dN = days[0], len(idx) - 1
        units, held, lp = 100.0 / spx[d0], {}, np.full(len(names), np.nan)
        eq, expo = np.full(len(idx), np.nan), []
        taken = skipped = 0
        for d in range(d0, dN + 1):
            row = C[d]
            lp = np.where(np.isfinite(row), row, lp)
            for t, (sh, ex) in list(held.items()):
                if d >= ex:
                    units += sh * lp[col[t]] / spx[d]
                    del held[t]
                    own.pop(t, None)
            vpos = sum(sh * lp[col[t]] for t, (sh, _) in held.items())
            equity = units * spx[d] + vpos
            for _, _, t, b_i in sorted(sigs.get(d, []), reverse=True):
                px = row[col[t]]
                if t in held or not np.isfinite(px):
                    continue
                if len(held) >= slots or sum(1 for x in own.values() if x == b_i) >= cap[b_i]:
                    skipped += 1
                    continue
                amt = equity / slots
                if units * spx[d] < amt * 0.999:
                    skipped += 1
                    continue
                units -= amt / spx[d]
                held[t] = (amt / px, d + hold)
                own[t] = b_i
                taken += 1
                vpos += amt
            eq[d] = equity
            expo.append(vpos / equity if equity > 0 else 0)
        return eq, float(np.mean(expo)), taken, skipped

    def pf_stats(eq, d0, dN):
        e = eq[d0:dN + 1]
        yrs = (idx[dN] - idx[d0]).days / 365.25
        return {"cagr": float((e[-1] / e[0]) ** (1 / yrs) - 1), "total": float(e[-1] / e[0] - 1),
                "mdd": float((e / np.maximum.accumulate(e) - 1).min())}

    def pf_out():
        d0, dN = days[0], len(idx) - 1
        scopes = {"valid": ("Acciones de validación (nunca usadas para elegir reglas)", (member.get("broad3") or set()) | (member.get("broad4") or set())),
                  "todas": ("Todas las acciones de EE.UU. del monitor", set(us_t))}
        yrs = sorted({idx[d].year for d in range(d0, dN + 1)})
        def yearly(eq):
            o_ = {}
            for y in yrs:
                ds = [d for d in range(d0, dN + 1) if idx[d].year == y]
                prev = [d for d in range(d0, dN + 1) if idx[d].year < y]
                a = eq[prev[-1]] if prev else eq[ds[0]]
                o_[str(y)] = float(eq[ds[-1]] / a - 1)
            return o_
        spx = close["SPY"].values.astype(float)
        spy_eq = np.full(len(idx), np.nan)
        spy_eq[d0:] = 100 * spx[d0:] / spx[d0]
        wk = list(range(d0, dN + 1, 5)) + ([dN] if (dN - d0) % 5 else [])
        out_ = {"slots": PF_SLOTS, "years": [str(y) for y in yrs], "partial": [str(yrs[0]), str(yrs[-1])],
                "dates": [str(idx[d].date()) for d in wk], "scopes": {}}
        for sk, (lbl, univ) in scopes.items():
            names = [t for t in us_t if t in univ]
            if not names:
                continue
            # referencia de igual peso: todas las acciones del grupo, rebalanceo anual (incluye el sesgo de supervivencia)
            C = close[names].values
            ew = np.full(len(idx), np.nan)
            v, start = 100.0, d0
            for y in yrs:
                ds = [d for d in range(d0, dN + 1) if idx[d].year == y]
                b = C[start]
                ok = np.isfinite(b) & (b > 0)
                for d in ds:
                    r_ = C[d][ok] / b[ok]
                    ew[d] = v * float(np.nanmean(r_)) if ok.any() else v
                v, start = ew[ds[-1]], ds[-1]
            ser = {"spy": {"label": "S&P 500 (SPY)", "years": yearly(spy_eq), **pf_stats(spy_eq, d0, dN), "curve": [round(float(spy_eq[d]), 2) for d in wk]},
                   "ew": {"label": "Todas las acciones del grupo, igual peso (referencia del sesgo)", "years": yearly(ew), **pf_stats(ew, d0, dN),
                          "curve": [round(float(ew[d]), 2) for d in wk]}}
            for k, (klbl, hold, key_) in PF_KEYS.items():
                r_ = portfolio(univ, key_, hold)
                if not r_:
                    continue
                eq, ex_, tk, sk_ = r_
                ser[k] = {"label": klbl, "years": yearly(eq), **pf_stats(eq, d0, dN), "exposure": ex_, "taken": tk, "skipped": sk_,
                          "curve": [round(float(eq[d]), 2) for d in wk]}
            out_["scopes"][sk] = {"label": lbl, "n": len(names), "series": ser}
        return out_

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
            "episodes": sorted([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k not in ("b", "c", "d", "m", "g") and not k.startswith("ind_")}
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

    def prob_safe():
        try:
            design = (member.get("broad") or set()) | (member.get("broad2") or set()) | (member.get("top") or set())
            valid = (member.get("broad3") or set()) | (member.get("broad4") or set())
            return prob_model(close, fund, meta, us_t, design - valid, valid, grp, mkx)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    def vars_safe():
        try:
            design = (member.get("broad") or set()) | (member.get("broad2") or set()) | (member.get("top") or set())
            valid = (member.get("broad3") or set()) | (member.get("broad4") or set())
            return var_analysis(close, fund, meta, us_t, design - valid, valid, mkx, KF)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    out = {
        "alerts": alerts_out(),
        "portfolio": pf_out(),
        "prob": prob_safe(),
        "vars": vars_safe(),
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
        # motor nuevo (PR3) con el camino que dio la señal: Comprar (T2) o Comprar en partes (checklist o barata)
        via_d = {}
        for k_, lbl_ in (("Y", "Barata contra su historia"), ("CR", "Checklist crecimiento"), ("CI", "Checklist cíclicas"), ("T2", "Comprar")):
            for e in r["eps"].get(k_, []):
                via_d[e["date"]] = lbl_          # si coinciden, gana el último de la lista (Comprar)
        pos_d = sorted(via_d)
        mot = []
        for e in r["eps"].get("PR3", []):
            # el camino: el de ese día, o el más reciente de las 20 ruedas previas
            v_ = via_d.get(e["date"])
            if v_ is None:
                prev_ = [d_ for d_ in pos_d if d_ <= e["date"]]
                v_ = via_d[prev_[-1]] if prev_ else "Motor"
            mot.append({"date": e["date"], "via": v_, "p": e.get("p"), **{h: r4(e.get(h)) for h in ("6m", "12m", "spy_6m", "spy_12m") if e.get(h) is not None}})
        per[t] = {"n": meta[t][0], "s": meta[t][1], "f": fund[t] is not None,
                  "w": [r4(x) for x in close[t].values[wk]],
                  "sig": sig, "mot": mot,
                  "dq": [{"date": e["date"], "via": e["setup"], "p": e.get("p"),
                          **{h: r4(e.get(h)) for h in ("6m", "12m", "spy_6m", "spy_12m") if e.get(h) is not None}}
                         for e in r["eps"].get("DQX", [])],
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
