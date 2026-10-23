"""
Bonos y letras en pesos que ajustan por CER, TAMAR o dólar linked (GitHub Actions, rfpesos.yml).

1) Lista: todos los bonos y letras de data912 (/live/arg_bonds y /live/arg_notes) que no son soberanos en dólares,
   BOPREAL ni LECAP/BONCAP (esos ya están en rentafija.json).
2) Ficha de cada uno en Rava: nombre, tipo, flujo de pagos, TIR y duration.
3) Índice CER y tasa TAMAR del BCRA (últimos 120 días).
Guarda rf_pesos.json (lo lee el monitor) y rf_pesos_debug.json (qué se leyó de cada uno).
"""
import datetime as dt
import json
import re
import time

import requests

from on_update import UA, texto, flujo_de_texto, num

HOY = dt.date.today()
SOB_USD = re.compile(r"^(AL|GD|AE|AO|AN)\d{2}[DC]?$|^BP")
LECAP = re.compile(r"^[ST]\d{2}[A-Z]\d$")


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


def candidatos(q):
    c = []
    for s, x in q.items():
        if SOB_USD.match(s) or LECAP.match(s):
            continue
        if s.endswith(("D", "C")) and s[:-1] in q:   # especie en dólares de un bono en pesos: se usa la de pesos
            continue
        if not (x.get("c") or 0) > 0:
            continue
        c.append(s)
    return sorted(c)


def tipo(nombre, tx):
    n = (nombre + " " + tx[:3000]).upper()
    if "DUAL" in n:
        return "DUAL"
    if "TAMAR" in n or "BADLAR" in n:
        return "TAMAR"
    if "LINKED" in n or "LELINK" in n or "D.LINK" in n or "DÓLAR LINK" in n or "DOLAR LINK" in n:
        return "DL"
    if "CER" in n or "BONCER" in n or "LECER" in n or "DISCOUNT" in n or "PAR $" in n or "CUASIPAR" in n:
        return "CER"
    return "OTRO"


def ficha(t):
    r = requests.get("https://www.rava.com/perfil/" + t, headers=UA, timeout=40)
    info = {"t": t, "http": r.status_code}
    if r.status_code != 200:
        return info, None
    h = r.text
    tx = texto(h)
    m = re.search(r"<title>(.*?)</title>", h, re.S)
    nombre = re.sub(r"\s*\|.*$", "", (m.group(1) if m else "")).strip()
    nombre = re.sub(r"^\S+\s+", "", nombre)
    nombre = re.sub(r"\s+\$\s?[\d.,]+.*$", "", nombre).strip()
    k = tx.find("Flujo de fondos")
    info["nombre"] = nombre
    info["texto_flujo"] = tx[max(0, k - 700):k + 900] if k >= 0 else tx[:1200]
    rows = flujo_de_texto(tx)
    tir = re.search(r"TIR\s*:?\s*(-?\d+,\d+)\s*%", tx)
    dur = re.search(r"Duration[^0-9]{0,30}(\d+,\d+)", tx, re.I)
    nota = re.search(r"(Pagos futuros[^.]{0,200}\.)", tx)
    act = re.search(r"actualizad\w*\s+(?:al\s+)?(\d{2}/\d{2}/\d{4})", tx, re.I)
    b = {"t": t, "nombre": nombre, "tipo": tipo(nombre, tx),
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
        if i >= 8 and info.get("tipo") not in ("CER", "TAMAR", "DL", "DUAL"):
            info.pop("texto_flujo", None)
        debug.append(info)
        if b and b["tipo"] != "OTRO" and b["flows"]:
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
