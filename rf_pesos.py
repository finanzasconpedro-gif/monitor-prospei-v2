"""
Bonos y letras en pesos que ajustan por CER, TAMAR o dólar linked (GitHub Actions, rfpesos.yml).

1) Lista: bonos y letras del Tesoro en pesos de data912 (/live/arg_bonds y /live/arg_notes), por ticker:
   CER (TZX.., TX.., Lecer X.., Discount, Par, Cuasipar), dólar linked (Lelink D.., TZV..) y TAMAR / duales.
2) Ficha de cada uno en Rava: nombre, tipo, flujo de pagos, TIR y duration.
3) Índice CER y tasa TAMAR del BCRA (últimos 120 días).
Guarda rf_pesos.json (lo lee el monitor) y rf_pesos_debug.json (qué se leyó de cada uno).
"""
import datetime as dt
import json
import re
import time

import requests

from on_update import UA, texto, num

HOY = dt.date.today()
TIPOS = [
    ("CER", re.compile(r"^(TZX[A-Z0-9]\d|TX\d{2}|X\d{2}[A-Z]\d|DICP|DIP0|PARP|PAP0|CUAP)$")),
    ("DL", re.compile(r"^(D\d{2}[A-Z]\d|TZV\d{2}|TZV[A-Z]\d)$")),
    ("DUAL", re.compile(r"^(TXM[A-Z]\d|TT[A-Z]\d{2}|TMVE\d)$")),
    ("TAMAR", re.compile(r"^(TM[A-Z]\d{2}|M\d{2}[A-Z]\d)$")),
]


def data912():
    out = {}
    for ep in ("arg_bonds", "arg_notes"):
        try:
            for x in requests.get("https://data912.com/live/" + ep, timeout=40).json():
                s = x.get("symbol") or ""
                if s:
                    out[s] = x
        except Exception as e:
            print("data912", ep, e)
    return out


def tipo_de(t):
    for k, rx in TIPOS:
        if rx.match(t):
            return k
    return None


def candidatos(q):
    return sorted(s for s, x in q.items() if tipo_de(s) and (x.get("c") or 0) > 0)


NUM = r"-?[\d.]*\d,\d+(?![\d/])"


def flujo(tx):
    """Tabla 'Fecha Interés Amort. Total [Saldo]' de Rava -> [fecha, interés, amortización]."""
    k = tx.find("Fecha Interés Amort. Total")
    if k < 0:
        return []
    seg = tx[k:k + 6000]
    fin = seg.find("Flujo actualizado")
    seg = seg[:fin] if fin > 0 else seg
    rows = []
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})((?:\s+(?:%s)){3,4})" % NUM, seg):
        n = [num(x) for x in m.group(2).split()]
        d, mo, y = m.group(1).split("/")
        i, a, tot = n[0], n[1], n[2]
        if abs(i + a - tot) > max(0.02, tot * 0.002):
            continue
        rows.append([f"{y}-{mo}-{d}", i, a])
    return rows


def ficha(t):
    r = requests.get("https://www.rava.com/perfil/" + t, headers=UA, timeout=40)
    info = {"t": t, "http": r.status_code}
    if r.status_code != 200:
        return info, None
    h = r.text
    tx = texto(h)
    m = re.search(r"<title>(.*?)</title>", h, re.S)
    n2 = re.search(r"(?:Bono|Letra|Obligación negociable)\s+" + re.escape(t) + r"\s+(?:" + re.escape(t) + r"\s+)?(.{2,80}?)\s+[\d.]+,\d+\s+-?[\d,]*%", tx)
    nombre = n2.group(1).strip() if n2 else t
    k = tx.find("Flujo de fondos")
    info["nombre"] = nombre
    info["texto_flujo"] = tx[max(0, k - 700):k + 900] if k >= 0 else tx[:1200]
    rows = flujo(tx)
    tir = re.search(r"TIR\s*:?\s*(-?\d+,\d+)\s*%", tx)
    dur = re.search(r"Duration[^0-9]{0,30}(\d+,\d+)", tx, re.I)
    nota = re.search(r"(Pagos futuros[^.]{0,200}\.)", tx)
    act = re.search(r"Flujo actualizado al (\d{2}/\d{2}/\d{4})", tx)
    b = {"t": t, "nombre": nombre, "tipo": tipo_de(t),
         "tir_rava": num(tir.group(1)) if tir else None, "dur_rava": num(dur.group(1)) if dur else None,
         "nota": nota.group(1) if nota else None, "flujo_al": act.group(1) if act else None,
         "flows": [x for x in rows if x[0] > HOY.isoformat()]}
    info["tipo"] = b["tipo"]
    info["n_flujos"] = len(b["flows"])
    return info, b


def bcra(var, dias=120):
    """Serie del BCRA (API de estadísticas). 30 = CER; 44 = TAMAR bancos privados (TNA)."""
    d0 = (HOY - dt.timedelta(days=dias)).isoformat()
    for url in (f"https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{var}?desde={d0}&hasta={HOY.isoformat()}&limit=500",
                f"https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/{var}?desde={d0}&hasta={HOY.isoformat()}&limit=500"):
        try:
            r = requests.get(url, timeout=40, verify=False)
            j = r.json()
            res = j.get("results") or []
            if res and isinstance(res[0], dict) and "detalle" in res[0]:   # v4: results[0].detalle
                res = res[0]["detalle"]
            serie = sorted([[x["fecha"][:10], float(x["valor"])] for x in res if "fecha" in x and "valor" in x])
            if serie:
                return serie, url
        except Exception as e:
            print("bcra", var, url, e)
    return [], None


def main():
    requests.packages.urllib3.disable_warnings()
    q = data912()
    cand = candidatos(q)
    print(len(cand), "bonos/letras en pesos a revisar")
    bonos, debug = [], []
    for i, t in enumerate(cand):
        try:
            info, b = ficha(t)
        except Exception as e:
            info, b = {"t": t, "error": str(e)}, None
        if info.get("tipo") == "CER" and info.get("n_flujos"):
            info.pop("texto_flujo", None)
        debug.append(info)
        if b and b["flows"]:
            b["v"] = q.get(t, {}).get("v")
            bonos.append(b)
        print(t, info.get("http"), info.get("tipo"), info.get("n_flujos"))
        time.sleep(0.8)
    cer, ucer = bcra(30)
    tamar, utam = bcra(44)
    out = {"updated": HOY.isoformat(), "cer": cer, "tamar": tamar, "bonos": bonos}
    with open("rf_pesos.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open("rf_pesos_debug.json", "w", encoding="utf-8") as f:
        json.dump({"cer_url": ucer, "cer_n": len(cer), "tamar_url": utam, "tamar_n": len(tamar),
                   "candidatos": cand, "detalle": debug}, f, ensure_ascii=False, indent=1)
    print("Guardados", len(bonos), "bonos · CER", len(cer), "datos · TAMAR", len(tamar), "datos")


if __name__ == "__main__":
    main()
