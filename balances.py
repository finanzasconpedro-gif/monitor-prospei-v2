"""
Panel de balances: quién presenta resultados hoy y en la semana, y el resumen de los que ya presentaron.

Se corre todos los días después del screener (screener.yml) y escribe balances.json:
  - upcoming : empresas que presentan en los próximos 7 días, con lo que esperan los analistas.
  - recent   : empresas que presentaron en los últimos 30 días, con el resumen de los números y la reacción
               del precio (ventas, márgenes, ganancia contra lo esperado, caja, cobranza, inventario).
  - cal      : última fecha de balance conocida de cada empresa (para saber quién ya presentó).
Los datos salen de Yahoo Finance. La guía de la empresa (lo que espera para el próximo trimestre) no viene en
datos estructurados: para eso se deja el enlace al comunicado en la SEC.
"""
import datetime as dt
import json
import math
import time

import os

import numpy as np
import pandas as pd
import requests

OUT = "balances.json"
UPCOMING_DAYS = 7
RECENT_DAYS = 30
FETCH_DAYS = 10          # se vuelven a bajar los números durante 10 días (Yahoo tarda en cargar el trimestre)


HOUR = {"bmo": "antes de la apertura", "amc": "después del cierre", "dmh": "durante la rueda"}


def finnhub_calendar(today):
    """Calendario de balances de Finnhub (gratis con clave): fecha, horario y ganancia por acción y ventas
    esperadas y reales, minutos después del anuncio. Sin clave (secreto FINNHUB_KEY) devuelve vacío."""
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        return {}
    out = {}
    try:
        r = requests.get("https://finnhub.io/api/v1/calendar/earnings",
                         params={"from": (today - dt.timedelta(days=FETCH_DAYS)).isoformat(),
                                 "to": (today + dt.timedelta(days=UPCOMING_DAYS)).isoformat(), "token": key}, timeout=30)
        r.raise_for_status()
        for x in r.json().get("earningsCalendar", []) or []:
            sym = str(x.get("symbol", "")).upper().replace(".", "-")
            out.setdefault(sym, []).append(x)
        print("Finnhub:", sum(len(v) for v in out.values()), "balances en el calendario")
    except Exception as e:
        print("Finnhub no disponible:", e)
    return out


def fh_near(fh, t, d, days=3):
    L = fh.get(t) or []
    try:
        d0 = dt.date.fromisoformat(d)
        L = [x for x in L if x.get("date") and abs((dt.date.fromisoformat(x["date"]) - d0).days) <= days]
    except Exception:
        return None
    return sorted(L, key=lambda x: x["date"])[-1] if L else None


def today_ar():
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).date()


def num(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def r4(x):
    x = num(x)
    return None if x is None else round(x, 4)


def row_of(df, *names):
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def at(series, i):
    try:
        return num(series.iloc[i]) if series is not None and len(series) > i else None
    except Exception:
        return None


def pct(a, b):
    return None if a is None or b is None or b == 0 else (a - b) / abs(b)


def estimates(tk):
    out = {}
    try:
        e = tk.earnings_estimate
        if e is not None and not e.empty and "0q" in e.index:
            q = e.loc["0q"]
            out.update(eps_est=r4(q.get("avg")), eps_ya=r4(q.get("yearAgoEps")), eps_n=num(q.get("numberOfAnalysts")))
    except Exception:
        pass
    try:
        rv = tk.revenue_estimate
        if rv is not None and not rv.empty and "0q" in rv.index:
            q = rv.loc["0q"]
            out.update(rev_est=num(q.get("avg")), rev_ya=num(q.get("yearAgoRevenue")))
    except Exception:
        pass
    return out


def results(tk, rdate):
    """Números del trimestre recién presentado. Devuelve None si Yahoo todavía no cargó ese trimestre."""
    inc = tk.quarterly_income_stmt
    if inc is None or inc.empty:
        return None
    inc = inc[sorted(inc.columns, reverse=True)]
    q0 = pd.Timestamp(inc.columns[0]).tz_localize(None) if pd.Timestamp(inc.columns[0]).tzinfo else pd.Timestamp(inc.columns[0])
    # el trimestre tiene que haber cerrado en los ~4 meses previos a la presentación
    # las empresas presentan entre 2 y 10 semanas después del cierre: si el último trimestre cargado es más viejo,
    # Yahoo todavía no cargó el que se acaba de presentar
    if not (0 <= (pd.Timestamp(rdate) - q0).days <= 80):
        return None
    rev = row_of(inc, "Total Revenue", "Operating Revenue")
    gp = row_of(inc, "Gross Profit")
    op = row_of(inc, "Operating Income")
    ni = row_of(inc, "Net Income", "Net Income Common Stockholders")
    eps = row_of(inc, "Diluted EPS", "Basic EPS")
    out = {"q_end": q0.strftime("%Y-%m-%d")}
    R0, R1, R4 = at(rev, 0), at(rev, 1), at(rev, 4)
    out["rev"] = R0
    out["rev_qoq"] = r4(pct(R0, R1))
    out["rev_yoy"] = r4(pct(R0, R4))
    if gp is not None and R0:
        g0, g1, g4 = at(gp, 0), at(gp, 1), at(gp, 4)
        out["gm"] = r4(g0 / R0) if g0 is not None else None
        out["gm_d1"] = r4(g0 / R0 - g1 / R1) if None not in (g0, g1) and R1 else None
        out["gm_d4"] = r4(g0 / R0 - g4 / R4) if None not in (g0, g4) and R4 else None
    if op is not None and R0:
        o0, o4 = at(op, 0), at(op, 4)
        out["om"] = r4(o0 / R0) if o0 is not None else None
        out["om_d4"] = r4(o0 / R0 - o4 / R4) if None not in (o0, o4) and R4 else None
    N0, N4 = at(ni, 0), at(ni, 4)
    out["ni"] = N0
    out["nm"] = r4(N0 / R0) if N0 is not None and R0 else None
    out["ni_yoy"] = r4(pct(N0, N4))
    E0, E4 = at(eps, 0), at(eps, 4)
    out["eps"] = r4(E0)
    out["eps_yoy"] = r4(pct(E0, E4))
    # caja y capital de trabajo
    try:
        bs = tk.quarterly_balance_sheet
        bs = bs[sorted(bs.columns, reverse=True)] if bs is not None and not bs.empty else None
        ar = row_of(bs, "Accounts Receivable", "Receivables")
        inv = row_of(bs, "Inventory")
        if ar is not None and R0 and R1:
            a0, a1 = at(ar, 0), at(ar, 1)
            out["dso"] = round(a0 / R0 * 91, 0) if a0 is not None else None
            out["dso_prev"] = round(a1 / R1 * 91, 0) if a1 is not None else None
        if inv is not None:
            i0, i1 = at(inv, 0), at(inv, 1)
            out["inv_qoq"] = r4(pct(i0, i1))
    except Exception:
        pass
    try:
        cf = tk.quarterly_cashflow
        cf = cf[sorted(cf.columns, reverse=True)] if cf is not None and not cf.empty else None
        ocf, fcf = row_of(cf, "Operating Cash Flow"), row_of(cf, "Free Cash Flow")
        c0 = at(ocf, 0)
        out["ocf"] = c0
        out["fcf"] = at(fcf, 0)
        out["ocf_ni"] = r4(c0 / N0) if c0 is not None and N0 and N0 > 0 else None
    except Exception:
        pass
    # ganancia contra lo esperado
    try:
        ed = tk.get_earnings_dates(limit=8)
        if ed is not None and not ed.empty:
            ed = ed.copy()
            ed.index = [pd.Timestamp(i).tz_localize(None) if pd.Timestamp(i).tzinfo else pd.Timestamp(i) for i in ed.index]
            near = [i for i in ed.index if abs((i.normalize() - pd.Timestamp(rdate)).days) <= 3]
            if near:
                rw = ed.loc[near[0]]
                out["eps_est"] = r4(rw.get("EPS Estimate"))
                out["eps_rep"] = r4(rw.get("Reported EPS"))
                s = num(rw.get("Surprise(%)"))
                out["surprise"] = r4(s / 100) if s is not None else None
    except Exception:
        pass
    return out


def reaction(tk, spy_hist, rdate):
    """Reacción del precio: del cierre previo al balance al cierre del día siguiente, contra el S&P 500."""
    try:
        h = tk.history(period="2mo", auto_adjust=True)["Close"]
        h.index = h.index.tz_localize(None) if h.index.tz is not None else h.index
        d = pd.Timestamp(rdate)
        before = h[h.index < d]
        after = h[h.index > d]
        if len(before) == 0 or len(after) == 0:
            return None, None
        p0, p1 = float(before.iloc[-1]), float(after.iloc[0])
        r = p1 / p0 - 1
        rs = None
        if spy_hist is not None:
            sb, sa = spy_hist[spy_hist.index < d], spy_hist[spy_hist.index > d]
            if len(sb) and len(sa):
                rs = r - (float(sa.iloc[0]) / float(sb.iloc[-1]) - 1)
        return r4(r), r4(rs)
    except Exception:
        return None, None


def fmtp(x, d=0):
    return f"{x*100:+.{d}f}%".replace(".", ",")


def notes(x):
    """Resumen automático: lo positivo y lo que hay que vigilar."""
    pos, neg = [], []
    ry, rq = x.get("rev_yoy"), x.get("rev_qoq")
    if ry is not None:
        (pos if ry >= 0.10 else neg if ry < 0 else pos).append(f"Ventas {fmtp(ry)} contra el mismo trimestre del año pasado" + (f" ({fmtp(rq)} contra el trimestre anterior)" if rq is not None else "") + ".")
    rs_ = x.get("rev_surp")
    if rs_ is not None:
        if rs_ >= 0.01:
            pos.append(f"Ventas {fmtp(rs_, 1)} arriba de lo que esperaban los analistas.")
        elif rs_ <= -0.01:
            neg.append(f"Ventas {fmtp(rs_, 1)} debajo de lo que esperaban los analistas.")
        else:
            pos.append("Ventas en línea con lo esperado.")
    s = x.get("surprise")
    if s is not None:
        if s >= 0.02:
            pos.append(f"La ganancia por acción superó lo que esperaban los analistas por {fmtp(s, 1)}.")
        elif s <= -0.02:
            neg.append(f"La ganancia por acción quedó {fmtp(s, 1)} debajo de lo que esperaban los analistas.")
        else:
            pos.append("La ganancia por acción salió en línea con lo esperado.")
    ey = x.get("eps_yoy")
    if ey is not None:
        (pos if ey > 0.05 else neg if ey < -0.05 else pos).append(f"Ganancia por acción {fmtp(ey)} contra el año anterior.")
    gm, g1, g4 = x.get("gm"), x.get("gm_d1"), x.get("gm_d4")
    if gm is not None:
        txt = f"Margen bruto de {gm*100:.1f}%".replace(".", ",")
        if g1 is not None:
            txt += f" ({g1*100:+.1f} pts contra el trimestre anterior".replace(".", ",") + (f", {g4*100:+.1f} pts contra el año pasado)".replace(".", ",") if g4 is not None else ")")
        txt += "."
        (neg if (g1 is not None and g1 <= -0.01) or (g4 is not None and g4 <= -0.02) else pos).append(txt)
    oy = x.get("om_d4")
    if oy is not None and abs(oy) >= 0.02:
        (pos if oy > 0 else neg).append(f"Margen operativo {oy*100:+.1f} pts contra el año pasado.".replace(".", ",", 1))
    dso, dp = x.get("dso"), x.get("dso_prev")
    if dso is not None and dp:
        if dso - dp >= 7 and dso / dp - 1 >= 0.15:
            neg.append(f"Cobra más lento: {dso:.0f} días de ventas en cuentas a cobrar contra {dp:.0f} el trimestre anterior.")
    iq = x.get("inv_qoq")
    if iq is not None and rq is not None and iq - rq >= 0.10 and iq >= 0.10:
        neg.append(f"El inventario creció {fmtp(iq)} en el trimestre, más rápido que las ventas ({fmtp(rq)}).")
    on = x.get("ocf_ni")
    if on is not None:
        if on >= 0.9:
            pos.append(f"Ganancia respaldada por caja: el flujo operativo fue {on:.1f} veces la ganancia.".replace(".", ",", 1))
        elif on < 0.6:
            neg.append(f"El flujo de caja operativo fue solo {on:.1f} veces la ganancia: la plata entra más lento que lo que se gana.".replace(".", ",", 1))
    rr, rs = x.get("react"), x.get("react_rel")
    if rr is not None:
        txt = f"El mercado reaccionó {fmtp(rr, 1)} al día siguiente" + (f" ({fmtp(rs, 1)} contra el S&P 500)" if rs is not None else "") + "."
        (pos if rr >= 0 else neg).append(txt)
    return pos, neg


def main():
    import yfinance as yf
    data = json.load(open("data.json", encoding="utf-8"))
    rows = {r["t"]: r for r in data["rows"]}
    try:
        st = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        st = {}
    cal, done = st.get("cal", {}), {e["t"] + "|" + e["date"]: e for e in st.get("recent", [])}
    est = st.get("est", {})       # lo que esperaban los analistas antes de cada balance (ticker|fecha)
    today = today_ar()
    # 1) calendario: próxima fecha de cada empresa según Yahoo
    for t, r in rows.items():
        ed = r.get("earn_days")
        if ed is not None and 0 <= ed <= 60:
            d = (today + dt.timedelta(days=int(ed))).isoformat()
            prev = cal.get(t)
            if prev and prev < today.isoformat() and (today - dt.date.fromisoformat(prev)).days <= RECENT_DAYS:
                cal[t + "|prev"] = prev          # se conserva la fecha que ya pasó
            cal[t] = d
    # 1b) primera corrida: busca quiénes presentaron en los últimos días (Yahoo ya muestra su próxima fecha,
    # a unos 3 meses), para no arrancar con la lista de "ya presentaron" vacía
    if not st:
        for t, r in rows.items():
            ed = r.get("earn_days")
            if ed is None or ed < 60 or r.get("region") != "EE.UU.":
                continue
            try:
                dts = yf.Ticker(t).get_earnings_dates(limit=6)
                time.sleep(0.15)
                past = [pd.Timestamp(i).tz_localize(None) if pd.Timestamp(i).tzinfo else pd.Timestamp(i) for i in dts.index]
                past = [i.date() for i in past if 0 <= (today - i.date()).days <= FETCH_DAYS]
                if past:
                    cal[t + "|prev"] = max(past).isoformat()
            except Exception:
                pass
    # 1c) Finnhub: fechas exactas, horario y resultados apenas se anuncian
    fh = finnhub_calendar(today)
    fdate = {}
    for t, L in fh.items():
        if t not in rows:
            continue
        for x in L:
            d = x.get("date")
            if not d:
                continue
            if d <= today.isoformat():
                if (x.get("epsActual") is not None or x.get("revenueActual") is not None) or d == today.isoformat():
                    cal[t + "|prev"] = max(d, cal.get(t + "|prev", ""))
            else:
                fdate[t] = min(d, fdate.get(t, "9999"))
            if d == today.isoformat():
                fdate.setdefault(t, d)
    # 2) próximos 7 días
    upcoming = []
    for t, r in rows.items():
        ed = r.get("earn_days")
        if t in fdate:
            ed = (dt.date.fromisoformat(fdate[t]) - today).days
        if ed is None or not (0 <= ed <= UPCOMING_DAYS):
            continue
        e = {"t": t, "name": r.get("name"), "sector": r.get("sector"), "region": r.get("region"),
             "date": (today + dt.timedelta(days=int(ed))).isoformat(), "days": int(ed), "mcap": r.get("mcap"),
             "verdict": r.get("verdict"), "pe": r.get("pe"), "fpe": r.get("fpe")}
        fe = fh_near(fh, t, e["date"], 1)
        if fe:
            e["hour"] = HOUR.get(fe.get("hour"))
        try:
            e.update(estimates(yf.Ticker(t)))
            if fe:
                if e.get("eps_est") is None and fe.get("epsEstimate") is not None:
                    e["eps_est"] = r4(fe["epsEstimate"])
                if e.get("rev_est") is None and fe.get("revenueEstimate"):
                    e["rev_est"] = num(fe["revenueEstimate"])
            if e.get("eps_est") is not None or e.get("rev_est") is not None:
                est[t + "|" + e["date"]] = {k: e.get(k) for k in ("eps_est", "rev_est", "eps_n", "eps_ya", "rev_ya")}
            time.sleep(0.2)
        except Exception:
            pass
        upcoming.append(e)
    upcoming.sort(key=lambda e: (e["date"], -(e.get("mcap") or 0)))
    # 3) los que ya presentaron (fecha en los últimos días)
    passed = {}
    for k, d in cal.items():
        t = k.split("|")[0]
        if t not in rows:
            continue
        try:
            dd = dt.date.fromisoformat(d)
        except Exception:
            continue
        if 0 <= (today - dd).days <= FETCH_DAYS:
            passed[t + "|" + d] = (t, d)
    try:
        spy = yf.Ticker("SPY").history(period="2mo", auto_adjust=True)["Close"]
        spy.index = spy.index.tz_localize(None) if spy.index.tz is not None else spy.index
    except Exception:
        spy = None
    n_new = 0
    for key, (t, d) in passed.items():
        old = done.get(key)
        if old and old.get("complete"):
            continue
        r = rows[t]
        try:
            tk = yf.Ticker(t)
            x = results(tk, d)
            time.sleep(0.2)
        except Exception as e:
            print("  balance sin datos", t, e)
            x = None
        e = {"t": t, "name": r.get("name"), "sector": r.get("sector"), "region": r.get("region"), "date": d,
             "mcap": r.get("mcap"), "verdict": r.get("verdict"), "complete": False}
        ex = est.get(key)
        if not ex:      # la fecha estimada pudo moverse uno o dos días
            dd0 = dt.date.fromisoformat(d)
            near = [v for k, v in est.items() if k.split("|")[0] == t and abs((dt.date.fromisoformat(k.split("|")[1]) - dd0).days) <= 4]
            ex = near[-1] if near else {}
        e["eps_exp"] = ex.get("eps_est")
        e["rev_exp"] = ex.get("rev_est")
        fe = fh_near(fh, t, d)
        if fe:
            e["hour"] = HOUR.get(fe.get("hour"))
            if e["eps_exp"] is None and fe.get("epsEstimate") is not None:
                e["eps_exp"] = r4(fe["epsEstimate"])
            if e["rev_exp"] is None and fe.get("revenueEstimate"):
                e["rev_exp"] = num(fe["revenueEstimate"])
            if fe.get("epsActual") is not None:
                e["eps_rep"] = r4(fe["epsActual"])
            if fe.get("revenueActual"):
                e["rev_real"] = num(fe["revenueActual"])
        if x:
            e.update({k: v for k, v in x.items() if v is not None or k not in e})
            if x.get("eps_est") is not None:          # estimado que informa Yahoo junto con el resultado
                e["eps_exp"] = x["eps_est"]
            e["react"], e["react_rel"] = reaction(tk, spy, d)
            e["complete"] = e.get("react") is not None and (today - dt.date.fromisoformat(d)).days >= 2
            n_new += 1
        elif old and old.get("rev") is not None:
            q_old = old.get("q_end")
            if not q_old or (dt.date.fromisoformat(d) - dt.date.fromisoformat(q_old)).days <= 80:
                continue          # se conserva lo que ya había
        elif fe and (e.get("eps_rep") is not None or e.get("rev_real")):
            try:
                e["react"], e["react_rel"] = reaction(yf.Ticker(t), spy, d)
            except Exception:
                pass
        elif old:
            continue
        # real y esperado de la misma fuente, para que la comparación sea pareja
        if fe and fe.get("epsActual") is not None and fe.get("epsEstimate") is not None and not (x and x.get("eps_rep") is not None and x.get("eps_est") is not None):
            e["eps_rep"], e["eps_exp"], e["surprise"] = r4(fe["epsActual"]), r4(fe["epsEstimate"]), None
        if fe and fe.get("revenueActual") and fe.get("revenueEstimate"):
            e["rev_real"], e["rev_exp"] = num(fe["revenueActual"]), num(fe["revenueEstimate"])
            rr = e["rev_real"]
        else:
            rr = e.get("rev") if e.get("rev") is not None else e.get("rev_real")
        e["rev_real"] = rr
        e["rev_surp"] = r4(rr / e["rev_exp"] - 1) if rr and e.get("rev_exp") else None
        if e.get("surprise") is None and e.get("eps_rep") is not None and e.get("eps_exp"):
            e["surprise"] = r4((e["eps_rep"] - e["eps_exp"]) / abs(e["eps_exp"]))
        e["pos"], e["neg"] = notes(e)
        done[key] = e
    lim = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
    recent = sorted([e for e in done.values() if e["date"] >= lim], key=lambda e: (e["date"], e.get("mcap") or 0), reverse=True)
    cal = {k: v for k, v in cal.items() if not k.endswith("|prev") or v >= lim}
    est = {k: v for k, v in est.items() if k.split("|")[1] >= lim}

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, (float, np.floating)):
            return None if not math.isfinite(float(o)) else float(o)
        if isinstance(o, np.integer):
            return int(o)
        return o

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(clean({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "today": today.isoformat(),
                         "upcoming": upcoming, "recent": recent, "cal": cal, "est": est}), f, ensure_ascii=False, separators=(",", ":"))
    print(f"Balances: {len(upcoming)} presentan en 7 días · {len(recent)} presentaron en {RECENT_DAYS} días ({n_new} actualizados hoy)")


if __name__ == "__main__":
    main()
