"""
Prueba de rotación de sectores con el gráfico de rotación relativa (RRG) del monitor: 10 años.

¿Se le gana al S&P 500 comprando los ETF sectoriales en ciertos cuadrantes del gráfico y vendiéndolos en otros?
Se usa exactamente el mismo cálculo que la pestaña Rotación (cierres semanales contra SPY):
  fuerza relativa = ETF / SPY suavizado · eje X (RS-Ratio) = fuerza / su promedio de 10 semanas · eje Y
  (RS-Momentum) = cambio de 4 semanas del eje X. Ambos centrados en 100.
Cada semana se decide con el cierre del viernes y se mantiene hasta el viernes siguiente. Se descuenta 0,10% por
cada compra o venta. Si una estrategia no elige ningún sector, queda en el S&P 500 (SPY).
Escribe rotacion.json para la página de control.
"""
import datetime as dt
import json
import math

import numpy as np
import pandas as pd

ETF = {"Tecnología": "XLK", "Salud": "XLV", "Financiero": "XLF", "Consumo discrecional": "XLY", "Comunicaciones": "XLC",
       "Industrial": "XLI", "Consumo básico": "XLP", "Energía": "XLE", "Utilities": "XLU", "Real estate": "XLRE",
       "Materiales": "XLB"}
BENCH = "SPY"
YEARS = 10
COST = 0.001            # 0,10% por operación (compra o venta)
SPLIT = "2022-01-01"


def quadrant(x, y):
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    if x >= 100:
        return "L" if y >= 100 else "P"
    return "M" if y >= 100 else "R"


QN = {"L": "Liderando", "P": "Perdiendo impulso", "M": "Mejorando", "R": "Rezagado"}


def rrg_series(px, spy):
    rs = (px / spy).ewm(span=3, adjust=False).mean()
    x = 100 * rs / rs.rolling(10).mean()
    y = (100 * x / x.shift(4)).ewm(span=3, adjust=False).mean()
    return x, y


# ---------------------------------------------------------------- estrategias: devuelven pesos por semana
def strat_quadrants(X, Y, keep):
    """Mantiene los sectores cuyo cuadrante está en 'keep'."""
    W = pd.DataFrame(0.0, index=X.index, columns=X.columns)
    for c in X.columns:
        q = [quadrant(a, b) for a, b in zip(X[c].values, Y[c].values)]
        W[c] = [1.0 if v in keep else 0.0 for v in q]
    return W


def strat_cross(X, Y):
    """Compra cuando cruza de Rezagado a Mejorando y mantiene hasta que vuelve a Rezagado."""
    W = pd.DataFrame(0.0, index=X.index, columns=X.columns)
    for c in X.columns:
        on, prev, out = False, None, []
        for a, b in zip(X[c].values, Y[c].values):
            q = quadrant(a, b)
            if q == "M" and prev == "R":
                on = True
            if q == "R":
                on = False
            out.append(1.0 if on else 0.0)
            prev = q if q else prev
        W[c] = out
    return W


def strat_heading(X, Y):
    """Mantiene los que van 'Rumbo a Liderando' o con 'Liderazgo firme' (dirección de las últimas 3 semanas)."""
    W = pd.DataFrame(0.0, index=X.index, columns=X.columns)
    dx, dy = X - X.shift(3), Y - Y.shift(3)
    for c in X.columns:
        out = []
        for a, b, ddx, ddy in zip(X[c].values, Y[c].values, dx[c].values, dy[c].values):
            q = quadrant(a, b)
            out.append(1.0 if (q == "M" and ddx > 0) or (q == "L" and ddy >= 0) else 0.0)
        W[c] = out
    return W


def strat_turn(X, Y, entry_q, exit_on="y", protect=False):
    """Compra cuando el punto está SUBIENDO (el impulso Y mayor que hace 3 semanas) dentro de los cuadrantes de
    entrada (Rezagado y/o Perdiendo impulso) y vende cuando llega a la mitad de la zona de arriba: impulso (Y) o
    fuerza (X) en la mediana histórica de Mejorando/Liderando (calculada solo con datos hasta ese día).
    protect=True: también vende si antes de llegar el impulso vuelve a caer dos semanas seguidas."""
    W = pd.DataFrame(0.0, index=X.index, columns=X.columns)
    dy = Y - Y.shift(3)
    # nivel "medio" de la zona alta, con la historia disponible hasta cada semana (sin mirar el futuro)
    upY = Y.where(Y >= 100).stack()
    upX = X.where((X >= 100) & (Y >= 100)).stack()
    midY = upY.groupby(level=0).median().expanding().median().reindex(X.index).ffill()
    midX = upX.groupby(level=0).median().expanding().median().reindex(X.index).ffill()
    for c in X.columns:
        on, down, out = False, 0, []
        for t, a, b, d_ in zip(X.index, X[c].values, Y[c].values, dy[c].values):
            q = quadrant(a, b)
            if q is None:
                out.append(0.0)
                continue
            if not on and q in entry_q and np.isfinite(d_) and d_ > 0:
                on, down = True, 0
            elif on:
                if exit_on == "y":
                    hit = q in ("M", "L") and np.isfinite(midY.get(t, np.nan)) and b >= midY[t]
                else:
                    hit = q == "L" and np.isfinite(midX.get(t, np.nan)) and a >= midX[t]
                down = down + 1 if (np.isfinite(d_) and d_ < 0) else 0
                if hit or (protect and down >= 2 and q in entry_q):
                    on = False
            out.append(1.0 if on else 0.0)
        W[c] = out
    return W


def strat_top(score, n, monthly=True):
    """Los n sectores con mayor puntaje; se rearma una vez por mes (o cada semana)."""
    W = pd.DataFrame(0.0, index=score.index, columns=score.columns)
    cur = None
    last_m = None
    for t in score.index:
        m = (t.year, t.month)
        if cur is None or not monthly or m != last_m:
            s = score.loc[t].dropna()
            cur = list(s.sort_values(ascending=False).index[:n]) if len(s) >= n else []
            last_m = m
        for c in cur:
            W.at[t, c] = 1.0
    return W


def simulate(W, R, spy_r, mkt=None):
    """W: pesos (1 = elegido) decididos al cierre de cada semana; R: retornos semanales de los ETF.
    Igual peso entre los elegidos; si no hay ninguno, SPY. mkt: si está en False, queda en efectivo."""
    W = W.copy()
    n = W.sum(axis=1)
    Wn = W.div(n.where(n > 0), axis=0).fillna(0.0)
    in_spy = (n == 0).astype(float)
    if mkt is not None:
        off = ~mkt.reindex(W.index).fillna(True).astype(bool)
        Wn.loc[off] = 0.0
        in_spy[off] = 0.0
    # retorno de la semana siguiente con los pesos decididos hoy
    ret = (Wn.shift(1) * R).sum(axis=1) + in_spy.shift(1).fillna(0) * spy_r
    full = pd.concat([Wn, in_spy.rename("SPY")], axis=1)
    turn = full.diff().abs().sum(axis=1).fillna(full.abs().sum(axis=1))
    ret = ret - turn.shift(1).fillna(0) * COST
    return ret.fillna(0.0), turn


def trades(W, px, spy, idx):
    """Cada compra y venta de la estrategia: semanas en cartera y resultado contra el S&P en ese lapso."""
    out = []
    for c in W.columns:
        w = W[c].reindex(idx).fillna(0).values
        i = 0
        while i < len(w):
            if w[i] > 0:
                j = i
                while j + 1 < len(w) and w[j + 1] > 0:
                    j += 1
                a, b = idx[i], idx[min(j + 1, len(idx) - 1)]
                if np.isfinite(px.at[a, c]) and np.isfinite(px.at[b, c]):
                    r = px.at[b, c] / px.at[a, c] - 1
                    rs = spy[b] / spy[a] - 1
                    out.append({"etf": c, "in": a.strftime("%Y-%m-%d"), "out": b.strftime("%Y-%m-%d") if j + 1 < len(w) else None,
                                "weeks": int(j - i + 1), "r": float(r), "rel": float(r - rs)})
                i = j + 1
            else:
                i += 1
    if not out:
        return None
    rel = np.array([t["rel"] for t in out])
    return {"n": len(out), "weeks": float(np.mean([t["weeks"] for t in out])), "win": float((rel > 0).mean()),
            "rel": float(rel.mean()), "rel_med": float(np.median(rel)),
            "last": sorted(out, key=lambda t: t["in"], reverse=True)[:12]}


def metrics(r, turn=None):
    r = r.dropna()
    if len(r) < 10:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 52.0
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = r.std() * math.sqrt(52)
    dd = float((eq / eq.cummax() - 1).min())
    out = {"cagr": float(cagr), "total": float(eq.iloc[-1] - 1), "vol": float(vol), "mdd": dd,
           "sharpe": float(cagr / vol) if vol > 0 else None}
    if turn is not None:
        out["trades_y"] = float(turn.reindex(r.index).sum() / 2 / yrs)
    return out


def yearly(r):
    g = (1 + r).groupby(r.index.year).prod() - 1
    return {str(k): float(v) for k, v in g.items()}


def main():
    import yfinance as yf
    tick = list(ETF.values()) + [BENCH]
    d = yf.download(tick, period="15y", interval="1d", auto_adjust=True, group_by="ticker", progress=False, threads=True)
    close = pd.DataFrame({t: d[t]["Close"] for t in tick if t in set(d.columns.get_level_values(0))})
    close.index = close.index.tz_localize(None) if close.index.tz is not None else close.index
    wk = close.resample("W-FRI").last()
    if wk.index[-1] > close.index[-1]:          # semana en curso: se rotula con el último día con precios
        wk.index = wk.index[:-1].append(pd.DatetimeIndex([close.index[-1]]))
    spy = wk[BENCH]
    secs = [c for c in ETF.values() if c in wk.columns]
    X, Y = {}, {}
    for c in secs:
        X[c], Y[c] = rrg_series(wk[c], spy)
    X, Y = pd.DataFrame(X), pd.DataFrame(Y)
    R = wk[secs].pct_change()
    spy_r = spy.pct_change()
    start = wk.index[-1] - pd.DateOffset(years=YEARS)
    idx = wk.index[wk.index >= start]
    # filtro de mercado: SPY arriba de su media de 40 semanas (~200 días)
    mkt = spy > spy.rolling(40).mean()
    rs13 = wk[secs].pct_change(13).sub(spy.pct_change(13), axis=0)          # fuerza relativa de 3 meses
    rs26 = wk[secs].pct_change(26).sub(spy.pct_change(26), axis=0)
    S = {
        "spy": ("Comprar y mantener el S&P 500 (SPY)", None),
        "eq": ("Todos los sectores en partes iguales", pd.DataFrame(1.0, index=wk.index, columns=secs).where(wk[secs].notna(), 0.0)),
        "lid": ("Mantener los sectores en Liderando; vender al salir de Liderando", strat_quadrants(X, Y, {"L"})),
        "mej_lid": ("Comprar en Mejorando o Liderando; vender al pasar a Perdiendo impulso", strat_quadrants(X, Y, {"M", "L"})),
        "lid_per": ("Mantener mientras la fuerza esté arriba de 100 (Liderando o Perdiendo impulso)", strat_quadrants(X, Y, {"L", "P"})),
        "cross": ("Comprar al pasar de Rezagado a Mejorando; vender al volver a Rezagado", strat_cross(X, Y)),
        "head": ("Comprar 'Rumbo a Liderando' o 'Liderazgo firme'; vender cuando cambia", strat_heading(X, Y)),
        "rez": ("Al revés (control): comprar los Rezagados", strat_quadrants(X, Y, {"R"})),
        "top3x": ("Los 3 sectores más fuertes del eje X (RS-Ratio), rearmado mensual", strat_top(X, 3)),
        "top3y": ("Los 3 sectores con más impulso (eje Y, RS-Momentum), rearmado mensual", strat_top(Y, 3)),
        "top3xy": ("Los 3 con mejor combinación de fuerza e impulso (X + Y), rearmado mensual", strat_top(X + Y, 3)),
        "top3m3": ("Los 3 que más le ganaron al S&P en 3 meses, rearmado mensual", strat_top(rs13, 3)),
        "top3m6": ("Los 3 que más le ganaron al S&P en 6 meses, rearmado mensual", strat_top(rs26, 3)),
        "giro": ("Comprar cuando sube dentro de Rezagado o Perdiendo impulso; vender al llegar al impulso medio de Mejorando/Liderando", strat_turn(X, Y, {"R", "P"})),
        "giro_x": ("Comprar cuando sube dentro de Rezagado o Perdiendo impulso; vender al llegar a la fuerza media de Liderando", strat_turn(X, Y, {"R", "P"}, "x")),
        "giro_p": ("Igual que 'giro', pero también vende si el impulso vuelve a caer 2 semanas antes de llegar", strat_turn(X, Y, {"R", "P"}, "y", True)),
        "giro_r": ("Solo desde Rezagado: comprar cuando sube; vender al impulso medio de Mejorando/Liderando", strat_turn(X, Y, {"R"})),
        "giro_pi": ("Solo desde Perdiendo impulso: comprar cuando retoma; vender al impulso medio de Mejorando/Liderando", strat_turn(X, Y, {"P"})),
    }
    out_s, curves = {}, {}
    for k, (lbl, W) in S.items():
        for filt in (False, True):
            if k == "spy" and filt:
                r_ = spy_r.where(mkt.shift(1).fillna(True).astype(bool), 0.0)
                turn = mkt.astype(int).diff().abs().fillna(0)
            elif k == "spy":
                r_, turn = spy_r, pd.Series(0.0, index=wk.index)
            else:
                r_, turn = simulate(W, R, spy_r, mkt if filt else None)
            r_ = r_.reindex(idx).fillna(0.0)
            key = k + ("_f" if filt else "")
            o = {"label": lbl + (" · con filtro de mercado (en efectivo si el S&P está debajo de su media de 40 semanas)" if filt else ""),
                 "all": metrics(r_, turn), "d": metrics(r_[r_.index < SPLIT]), "v": metrics(r_[r_.index >= SPLIT]),
                 "years": yearly(r_)}
            if W is not None:
                o["avg_n"] = float(W.reindex(idx).sum(axis=1).mean())
                if not filt and k not in ("eq",):
                    o["trades"] = trades(W, wk, spy, idx)
            out_s[key] = o
            curves[key] = [round(float(v), 4) for v in (1 + r_).cumprod().values]
    # diagnóstico: qué pasó después según el cuadrante y la dirección (rendimiento contra SPY)
    diag = {}
    for hn, hw in (("4s", 4), ("13s", 13), ("26s", 26)):
        fwd = wk[secs].shift(-hw) / wk[secs] - 1
        fspy = spy.shift(-hw) / spy - 1
        rel = fwd.sub(fspy, axis=0)
        dx, dy = X - X.shift(3), Y - Y.shift(3)
        for c in secs:
            for t in idx:
                if t not in rel.index or not np.isfinite(rel.at[t, c]):
                    continue
                q = quadrant(X.at[t, c], Y.at[t, c])
                if not q:
                    continue
                hd = {"L": "Liderazgo firme" if dy.at[t, c] >= 0 else "Empieza a frenarse",
                      "M": "Rumbo a Liderando" if dx.at[t, c] > 0 else "Mejorando sin avanzar",
                      "R": "Girando hacia Mejorando" if dy.at[t, c] > 0 else "Sigue rezagándose",
                      "P": "Retomando impulso" if dy.at[t, c] > 0 else "Rumbo a Rezagado"}[q]
                for kk in (QN[q], QN[q] + " · " + hd):
                    diag.setdefault(kk, {}).setdefault(hn, []).append(float(rel.at[t, c]))
    diag_out = {}
    for kk, v in diag.items():
        diag_out[kk] = {hn: {"n": len(L), "avg": float(np.mean(L)), "med": float(np.median(L)), "beat": float(np.mean(np.array(L) > 0))}
                        for hn, L in v.items()}
    # dónde está cada sector hoy
    now = []
    for c in secs:
        q = quadrant(X[c].iloc[-1], Y[c].iloc[-1])
        sec = next(s for s, e in ETF.items() if e == c)
        now.append({"etf": c, "sector": sec, "q": QN.get(q), "x": round(float(X[c].iloc[-1]), 2), "y": round(float(Y[c].iloc[-1]), 2),
                    "top3m6": bool(c in [k_ for k_ in rs26.iloc[-1].dropna().sort_values(ascending=False).index[:3]])})
    res = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "period": {"from": str(idx[0].date()), "to": str(idx[-1].date())}, "split": SPLIT, "cost": COST,
           "dates": [d_.strftime("%Y-%m-%d") for d_ in idx], "strategies": out_s, "curves": curves, "diag": diag_out, "now": now}

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, float):
            return None if not math.isfinite(o) else o
        return o
    with open("rotacion.json", "w", encoding="utf-8") as f:
        json.dump(clean(res), f, ensure_ascii=False, separators=(",", ":"))
    print(f"Rotación: {res['period']}")
    for k, v in sorted(out_s.items(), key=lambda kv: -(kv[1]["all"].get("cagr") or -9)):
        a = v["all"]
        print(f"  {k:10s} anual {a['cagr']*100:5.1f}% · máx. caída {a['mdd']*100:5.1f}% · vol {a['vol']*100:4.1f}% · "
              f"hasta 2021 {v['d'].get('cagr',0)*100:5.1f}% · desde 2022 {v['v'].get('cagr',0)*100:5.1f}%")


if __name__ == "__main__":
    main()
