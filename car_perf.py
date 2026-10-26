"""
Seguimiento de las carteras sugeridas de PROSPEI como si fueran un fondo común (cuotaparte base 100).
GitHub Actions (car_perf.yml): cada vez que se sube carteras.json y todos los días hábiles.

Lee los movimientos de cada cartera (carteras.json → "seguimiento"), arma la cuotaparte diaria desde el inicio
y la compara con su vara:
  conservadora → GOVT · moderada → 50% GOVT + 50% SPY · audaz → 20% XLK + 50% SPY + 30% GOVT (rebalanceo mensual).
Precios en dólares:
  acciones / CEDEARs / ETFs  → Yahoo (precio + dividendos)
  bonos soberanos             → data912 histórico (especie D, MEP) + cupones/amortizaciones de rentafija.json
  ONs                         → no hay histórico público: se guarda el cierre de cada día desde hoy (carteras_px.json);
                                antes de eso, se interpola entre el precio de compra que cargaste y el primer cierre guardado
  fondos (BCMMA, ESTRA1/3)    → cuotaparte diaria de CAFCI (argentinadatos); BCMMA está en pesos y se pasa al MEP del día
Salida: carteras_perf.json (lo lee el monitor) y carteras_px.json (precios guardados).
"""
import datetime as dt
import json
import math
import time

import pandas as pd
import requests

CAR, PX, OUT = "carteras.json", "carteras_px.json", "carteras_perf.json"
HOY = dt.date.today()
VARAS = {"conservadora": {"GOVT": 1.0}, "moderada": {"GOVT": 0.5, "SPY": 0.5}, "audaz": {"XLK": 0.2, "SPY": 0.5, "GOVT": 0.3}}
VARA_TXT = {"conservadora": "Bonos del Tesoro de EE.UU. (GOVT)", "moderada": "50% bonos del Tesoro (GOVT) + 50% S&P 500 (SPY)",
            "audaz": "20% tecnología (XLK) + 50% S&P 500 (SPY) + 30% bonos del Tesoro (GOVT)"}
FONDOS = {  # código → (nombre en CAFCI, moneda, categoría en argentinadatos)
    "BCMMA": ("balanz capital money market - clase a", "ARS", "mercadoDinero"),
    "ESTRA1": ("balanz capital estrategia i usd - clase a", "USD", "rentaFija"),
    "ESTRA3": ("balanz capital estrategia iii usd - clase a", "USD", "rentaFija"),
}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.append(s)


def jget(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=40, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1 + 2 * i)
    return None


def load(p, d):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


def ser(d):
    """dict fecha → valor  ⇒  pd.Series ordenada por fecha (índice Timestamp)."""
    if not d:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(k): float(v) for k, v in d.items() if v is not None and float(v) > 0}).sort_index()
    return s[~s.index.duplicated(keep="last")]


def asof(s, d):
    if s is None or s.empty:
        return None
    d = pd.Timestamp(d)
    x = s[:d]
    if len(x):
        return float(x.iloc[-1])
    return float(s.iloc[0])   # antes del primer dato: el primero conocido


# ------------------------------------------------------------------ precios
def yahoo(tickers, start, adjusted):
    import yfinance as yf
    out = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(start=start, auto_adjust=adjusted, actions=True)
            if h is None or h.empty:
                log("Yahoo sin datos:", t)
                continue
            idx = h.index.tz_localize(None) if getattr(h.index, "tz", None) is not None else h.index
            idx = pd.to_datetime(idx.date)
            px = pd.Series(h["Close"].values, index=idx)
            dv = pd.Series(h["Dividends"].values, index=idx) if "Dividends" in h else pd.Series(dtype=float)
            out[t] = (px[px > 0], dv[dv > 0])
        except Exception as e:
            log("Yahoo error", t, e)
    return out


def data912_hist(t):
    j = jget("https://data912.com/historical/bonds/" + t)
    if not isinstance(j, list):
        return pd.Series(dtype=float)
    return ser({x["date"]: x.get("c") for x in j if x.get("date") and x.get("c")})


def fondos_hist(codes, start, store):
    """Cuotaparte diaria de cada fondo desde 'start'. Lo ya bajado queda en store['fondo'] (no se vuelve a pedir)."""
    st = store.setdefault("fondo", {})
    cats = sorted({FONDOS[c][2] for c in codes})
    tried = store.setdefault("fondo_dias", {})
    d = start
    while d <= HOY:
        if d.weekday() < 5:
            ds = d.isoformat()
            for cat in cats:
                key = cat + ":" + ds
                need = [c for c in codes if FONDOS[c][2] == cat and ds not in st.get(c, {})]
                if not need or tried.get(key, 0) >= (3 if (HOY - d).days > 5 else 99):
                    continue
                j = jget("https://api.argentinadatos.com/v1/finanzas/fci/" + cat + "/" + d.strftime("%Y/%m/%d"), tries=2)
                tried[key] = tried.get(key, 0) + 1
                if isinstance(j, list):
                    for x in j:
                        n = str(x.get("fondo", "")).lower()
                        for c in need:
                            if n.startswith(FONDOS[c][0]) and x.get("vcp"):
                                st.setdefault(c, {})[ds] = float(x["vcp"])
        d += dt.timedelta(days=1)
    for cat in cats:   # último dato publicado
        j = jget("https://api.argentinadatos.com/v1/finanzas/fci/" + cat + "/ultimo")
        for x in j or []:
            n = str(x.get("fondo", "")).lower()
            for c in codes:
                if FONDOS[c][2] == cat and n.startswith(FONDOS[c][0]) and x.get("vcp") and x.get("fecha"):
                    st.setdefault(c, {})[str(x["fecha"])[:10]] = float(x["vcp"])
    return {c: ser(st.get(c, {})) for c in codes}


def snapshot_ons(store):
    """Guarda el cierre de hoy de todas las ONs en dólares MEP (data912 no tiene histórico de ONs)."""
    j = jget("https://data912.com/live/arg_corp")
    st = store.setdefault("on", {})
    n = 0
    for x in j or []:
        s = str(x.get("symbol", ""))
        if s.endswith("D") and (x.get("c") or 0) > 0:
            st.setdefault(s[:-1], {})[HOY.isoformat()] = float(x["c"])
            n += 1
    log("ONs guardadas hoy:", n)


# ------------------------------------------------------------------ cupones
def flujos_sob():
    rf = load("rentafija.json", {})
    return {b["t"]: b["flows"] for b in rf.get("bonds", [])}


def flujos_on():
    """Flujos futuros (Rava) + cupones pasados estimados con la tasa y la frecuencia (los pasados no se publican)."""
    out = {}
    for o in load("ons.json", {}).get("ons", []):
        fl = [list(f) for f in o.get("flows", [])]
        per = {"Mensual": 1, "Trimestral": 3, "Semestral": 6, "Anual": 12}.get(o.get("frec"), 6)
        if fl and o.get("cup"):
            res = fl[0][3] or 100
            c = res * float(o["cup"]) / 100 * per / 12
            d = pd.Timestamp(fl[0][0])
            for _ in range(8):
                d = d - pd.DateOffset(months=per)
                fl.insert(0, [d.date().isoformat(), c, 0.0, res])
        out[o["t"]] = fl
    return out


# ------------------------------------------------------------------ simulación
def norm_t(clase, t):
    t = str(t).upper().strip()
    if clase == "on":
        return t[:-1] if len(t) == 5 and t[-1] in "ODC" else t
    return t


def simular(c, P, sob_fl, on_fl):
    sg = c["seguimiento"]
    ini = pd.Timestamp(sg.get("inicio", "2026-01-01"))
    cap = float(sg.get("capital", 100000))
    movs = sorted(sg.get("movs", []), key=lambda m: (m["f"], {"aporte": 0, "retiro": 1, "venta": 2, "compra": 3}.get(m["tipo"], 9)))
    dias = [d for d in P["cal"] if d >= ini]
    if not dias:
        return None
    pos = {}          # clave → dict(units, cost, inv, rec, inc, clase, t)
    cash, cuotas = cap, cap / 100.0
    serie, avisos = [], []
    mi = 0

    def precio(clase, t, d):
        if clase == "accion":
            s = P["acc"].get(t)
            return asof(s[0], d) if s else None
        if clase == "sob":
            return asof(P["sob"].get(t), d)
        if clase == "on":
            return asof(P["on"].get(t), d)
        if clase == "fondo":
            return asof(P["fondo"].get(t), d)
        return None

    def valor_unit(clase, t, d, px=None):
        px = px if px is not None else precio(clase, t, d)
        if px is None:
            return None
        if clase in ("sob", "on"):
            return px / 100.0
        if clase == "fondo" and FONDOS.get(t, ("", "USD"))[1] == "ARS":
            mep = asof(P["mep"], d)
            return px / mep if mep else None
        return px

    prev = None
    for d in dias:
        # dividendos y cupones de lo que se tenía al cierre anterior
        for k, p in pos.items():
            if p["units"] <= 0:
                continue
            inc = 0.0
            if p["clase"] == "accion" and P["acc"].get(p["t"]):
                dv = P["acc"][p["t"]][1]
                if prev is not None and len(dv):
                    inc = float(dv[(dv.index > prev) & (dv.index <= d)].sum()) * p["units"]
            elif p["clase"] in ("sob", "on"):
                fl = (sob_fl if p["clase"] == "sob" else on_fl).get(p["t"], [])
                for f in fl:
                    fd = pd.Timestamp(f[0])
                    if prev is not None and prev < fd <= d and fd > p["desde"]:
                        inc += p["units"] / 100.0 * (f[1] + f[2])
            if inc:
                cash += inc
                p["inc"] += inc

        def V():
            v = cash
            for p in pos.values():
                if p["units"] > 0:
                    u = valor_unit(p["clase"], p["t"], d)
                    v += p["units"] * (u if u is not None else p["last"])
                    if u is not None:
                        p["last"] = u
            return v

        nav = V() / cuotas
        while mi < len(movs) and pd.Timestamp(movs[mi]["f"]) <= d:
            m = movs[mi]
            mi += 1
            tipo, usd = m["tipo"], float(m.get("usd") or 0)
            if tipo == "aporte":
                cash += usd
                cuotas += usd / nav
                continue
            if tipo == "retiro":
                cash -= usd
                cuotas -= usd / nav
                continue
            clase, t = m.get("clase"), norm_t(m.get("clase"), m.get("t"))
            k = clase + ":" + t
            u = valor_unit(clase, t, d, float(m["precio"]) if m.get("precio") else None)
            if u is None or u <= 0:
                avisos.append(f"{m['f']} {tipo} {t}: no hay precio para esa fecha; cargá el precio de compra/venta.")
                continue
            p = pos.setdefault(k, {"units": 0.0, "cost": 0.0, "inv": 0.0, "rec": 0.0, "inc": 0.0, "clase": clase, "t": t,
                                   "last": u, "desde": d, "primera": m["f"], "ultima": None})
            if tipo == "compra":
                n = usd / u
                p["units"] += n
                p["cost"] += usd
                p["inv"] += usd
                cash -= usd
                p["last"] = u
            elif tipo == "venta":
                n = p["units"] if m.get("todo") or usd <= 0 else min(p["units"], usd / u)
                if p["units"] <= 0:
                    avisos.append(f"{m['f']} venta {t}: no había tenencia.")
                    continue
                frac = n / p["units"]
                p["cost"] -= p["cost"] * frac
                p["units"] -= n
                p["rec"] += n * u
                cash += n * u
                p["ultima"] = m["f"]
                if p["units"] < 1e-9:
                    p["units"] = 0.0
        if cash < -1:
            avisos.append(f"{d.date()}: la liquidez quedó negativa (US$ {cash:,.0f}); revisá montos o cargá un aporte.")
        nav = V() / cuotas
        serie.append((d, nav))
        prev = d

    # vara
    w = VARAS.get(sg.get("vara") or c.get("id"), VARAS["moderada"])
    b_idx, units, mes = [], {}, None
    val = 100.0
    for d, _ in serie:
        pr = {t: asof(P["bench"].get(t), d) for t in w}
        if any(v is None for v in pr.values()):
            b_idx.append(None)
            continue
        if mes != (d.year, d.month):   # rebalanceo mensual
            if units:
                val = sum(units[t] * pr[t] for t in w)
            units = {t: val * w[t] / pr[t] for t in w}
            mes = (d.year, d.month)
        val = sum(units[t] * pr[t] for t in w)
        b_idx.append(val)

    # resultados
    fechas = [d for d, _ in serie]
    navs = [n for _, n in serie]

    def ret(arr, dias_atras=None, desde=None):
        if not arr or arr[-1] is None:
            return None
        if desde is not None:
            i = next((j for j, f in enumerate(fechas) if f >= desde), None)
        else:
            lim = fechas[-1] - pd.Timedelta(days=dias_atras)
            i = max([j for j, f in enumerate(fechas) if f <= lim] or [0])
        if i is None or arr[i] in (None, 0):
            return None
        return arr[-1] / arr[i] - 1

    def stats(arr):
        a = [x for x in arr if x]
        if len(a) < 3:
            return None, None
        r = pd.Series(a).pct_change().dropna()
        vol = float(r.std() * math.sqrt(252))
        pk, dd = a[0], 0.0
        for x in a:
            pk = max(pk, x)
            dd = min(dd, x / pk - 1)
        return vol, dd

    y0 = pd.Timestamp(HOY.year, 1, 1)
    met = {}
    for nm, arr in (("cartera", navs), ("vara", b_idx)):
        vol, dd = stats(arr)
        met[nm] = {"inicio": ret(arr, desde=fechas[0]) if arr and arr[0] else None, "anio": ret(arr, desde=y0),
                   "m1": ret(arr, 30), "m3": ret(arr, 91), "vol": vol, "maxdd": dd}
    dlast = fechas[-1]
    tot = navs[-1] * cuotas
    abiertas, cerradas = [], []
    for p in pos.values():
        u = valor_unit(p["clase"], p["t"], dlast)
        u = u if u is not None else p["last"]
        valor = p["units"] * u
        gan = valor + p["rec"] + p["inc"] - p["inv"]
        row = {"t": p["t"] + ("O" if p["clase"] == "on" else ""), "clase": p["clase"], "desde": p["primera"],
               "invertido": round(p["inv"], 2), "cobrado": round(p["rec"] + p["inc"], 2), "ganancia": round(gan, 2),
               "rend": round(gan / p["inv"], 4) if p["inv"] else None, "aporte": round(gan / cap, 4)}
        if p["units"] > 0:
            px = precio(p["clase"], p["t"], dlast)
            row.update(cantidad=round(p["units"], 4), precio=round(px, 4) if px else None, valor=round(valor, 2),
                       peso=round(valor / tot, 4) if tot else None, costo=round(p["cost"], 2))
            abiertas.append(row)
        else:
            row.update(hasta=p["ultima"])
            cerradas.append(row)
    abiertas.sort(key=lambda r: -(r.get("valor") or 0))
    paso = max(1, len(serie) // 260)
    puntos = [[f.date().isoformat(), round(n, 4), round(b, 4) if b else None] for i, (f, n, b) in
              enumerate(zip(fechas, navs, b_idx)) if i % paso == 0 or i == len(serie) - 1]
    return {"id": c["id"], "nombre": c.get("nombre"), "inicio": ini.date().isoformat(), "capital": cap,
            "vara": VARA_TXT.get(sg.get("vara") or c.get("id"), ""), "al": dlast.date().isoformat(),
            "cuotaparte": round(navs[-1], 4), "patrimonio": round(tot, 2), "liquidez": round(cash, 2),
            "liquidez_peso": round(cash / tot, 4) if tot else None, "metricas": met, "serie": puntos,
            "abiertas": abiertas, "cerradas": cerradas, "avisos": avisos[:30]}


def main():
    D = load(CAR, {"carteras": []})
    store = load(PX, {})
    snapshot_ons(store)
    tr = [c for c in D.get("carteras", []) if c.get("seguimiento") and c["seguimiento"].get("movs") is not None]
    if not tr:
        log("Ninguna cartera con seguimiento todavía.")
    ini = min([pd.Timestamp(c["seguimiento"].get("inicio", "2026-01-01")) for c in tr] or [pd.Timestamp(HOY)])
    start = (ini - pd.Timedelta(days=10)).date()
    need = {"accion": set(), "sob": set(), "on": set(), "fondo": set()}
    for c in tr:
        for m in c["seguimiento"]["movs"]:
            if m.get("clase") in need:
                need[m["clase"]].add(norm_t(m["clase"], m["t"]))
    P = {}
    bench_t = sorted({t for w in VARAS.values() for t in w})
    yb = yahoo(bench_t, start.isoformat(), adjusted=True)
    P["bench"] = {t: v[0] for t, v in yb.items()}
    P["acc"] = yahoo(sorted(need["accion"]), start.isoformat(), adjusted=False) if need["accion"] else {}
    cal = P["bench"].get("SPY")
    P["cal"] = list(cal.index) if cal is not None else list(pd.bdate_range(ini, HOY))
    if pd.Timestamp(HOY) not in P["cal"] and HOY.weekday() < 5:
        P["cal"].append(pd.Timestamp(HOY))
    P["sob"] = {}
    for t in need["sob"]:
        s = data912_hist(t + "D")
        if s.empty:
            log("Sin histórico en data912:", t, "(se usan los cierres guardados y el precio de compra)")
            s = ser(store.get("sob", {}).get(t, {}))
        P["sob"][t] = s
    a, b = data912_hist("AL30"), data912_hist("AL30D")
    P["mep"] = (a / b).dropna() if not a.empty and not b.empty else pd.Series(dtype=float)
    # ONs: cierres guardados + precio de compra al principio (interpolación lineal hasta el primer cierre guardado)
    P["on"] = {}
    for t in need["on"]:
        s = ser(store.get("on", {}).get(t, {}))
        compras = [(pd.Timestamp(m["f"]), float(m["precio"])) for c in tr for m in c["seguimiento"]["movs"]
                   if m.get("clase") == "on" and norm_t("on", m["t"]) == t and m.get("precio")]
        if compras:
            f0, p0 = min(compras)
            if s.empty:
                s = pd.Series({f0: p0})
            elif f0 < s.index[0]:
                rng = [d for d in P["cal"] if f0 <= d < s.index[0]]
                p1, n = float(s.iloc[0]), max(1, len(rng))
                s = pd.concat([pd.Series({d: p0 + (p1 - p0) * i / n for i, d in enumerate(rng)}), s]).sort_index()
        if s.empty:
            log("ON sin precio:", t, "— cargá el precio de compra en el movimiento.")
        P["on"][t] = s
    P["fondo"] = fondos_hist(sorted(t for t in need["fondo"] if t in FONDOS), ini.date(), store) if need["fondo"] else {}
    res = []
    sob_fl, on_fl = flujos_sob(), flujos_on()
    for c in tr:
        try:
            r = simular(c, P, sob_fl, on_fl)
            if r:
                res.append(r)
                log(c["id"], "cuotaparte", r["cuotaparte"], "vara", r["serie"][-1][2] if r["serie"] else None)
        except Exception as e:
            log("Error en", c.get("id"), repr(e))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.utcnow().isoformat(timespec="minutes") + "Z", "carteras": res, "log": LOG[-60:]},
                  f, ensure_ascii=False, separators=(",", ":"))
    with open(PX, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
