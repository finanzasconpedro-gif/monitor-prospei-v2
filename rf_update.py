"""
Mantiene rentafija.json con las LECAP y BONCAP nuevas (GitHub Actions, rentafija.yml).

Dos formas de uso:
  1) Manual (Actions -> Renta fija PROSPEI -> Run workflow, completando ticker, tipo, emisión, vencimiento y TEM):
     calcula el valor final y lo agrega (o lo corrige) en rentafija.json.
  2) Automática (todas las semanas): lee los anuncios de resultados de licitación de la Secretaría de Finanzas
     (argentina.gob.ar), detecta las LECAP/BONCAP que todavía no están cargadas y las agrega si todos los datos
     se leyeron bien y la TEM que surge del precio de mercado es razonable. Todo lo que encuentra (lo cargado y
     lo descartado, con el texto de origen) queda en rf_auto_log.json para poder revisarlo.

Valor final = 100 x (1 + TEM) ^ (días 30/360 entre emisión y vencimiento / 30)
(convención verificada: T30A7, TEM 2,55% del 31/10/2025 al 30/04/2027 -> 157,34; S29E7 -> 111,68).
"""
import datetime as dt
import json
import os
import re
import sys
import time

import requests

RF = "rentafija.json"
LOG = "rf_auto_log.json"
UA = {"User-Agent": "Mozilla/5.0 (PROSPEI monitor; github.com/finanzasconpedro-gif)"}
MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
         "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}
LISTADOS = [   # páginas donde se publican los anuncios (se prueban todas; alcanza con que una funcione)
    "https://www.argentina.gob.ar/economia/finanzas/noticias",
    "https://www.argentina.gob.ar/noticias?field_tags_target_id=All&search_api_fulltext=licitaci%C3%B3n",
    "https://www.argentina.gob.ar/economia/noticias",
]


def d360(a, b):
    """Días entre dos fechas con la convención 30/360."""
    d1, d2 = min(a.day, 30), b.day
    if d1 == 30 and d2 == 31:
        d2 = 30
    return (b.year - a.year) * 360 + (b.month - a.month) * 30 + (d2 - d1)


def valor_final(emision, venc, tem):
    return round(100 * (1 + tem) ** (d360(emision, venc) / 30), 2)


def load():
    with open(RF, encoding="utf-8") as f:
        return json.load(f)


def save(rf):
    rf["updated"] = dt.date.today().isoformat()
    with open(RF, "w", encoding="utf-8") as f:
        json.dump(rf, f, ensure_ascii=False, separators=(",", ":"))


def upsert(rf, t, fam, emision, venc, tem, fuente):
    vf = valor_final(emision, venc, tem)
    row = {"t": t, "fam": fam, "venc": venc.isoformat(), "vf": vf, "emision": emision.isoformat(),
           "tem_emision": round(tem, 6), "fuente": fuente}
    L = [x for x in rf["lecaps"] if x["t"] != t]
    L.append(row)
    rf["lecaps"] = sorted(L, key=lambda x: x["venc"])
    return row


def parse_fecha(s):
    s = s.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", s)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        return dt.date(y, int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})", s.upper())
    if m and m.group(2) in MESES:
        return dt.date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    raise ValueError("fecha no reconocida: " + s)


def manual():
    t = os.environ.get("RF_TICKER", "").strip().upper()
    if not t:
        return False
    fam = (os.environ.get("RF_TIPO") or "LECAP").strip().upper()
    em = parse_fecha(os.environ["RF_EMISION"])
    ve = parse_fecha(os.environ["RF_VENC"])
    tem = float(os.environ["RF_TEM"].replace(",", ".").replace("%", "")) / 100
    rf = load()
    row = upsert(rf, t, fam, em, ve, tem, "carga manual")
    save(rf)
    print("Cargado:", row)
    return True


# ------------------------------------------------------------------ automático
def texto(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", html)


def get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.text


def links_licitacion():
    out = []
    for u in LISTADOS:
        try:
            h = get(u)
        except Exception as e:
            print("  sin listado", u, e)
            continue
        for href in re.findall(r'href="(/noticias/[^"#?]+)"', h):
            if "licitac" in href and href not in out:
                out.append(href)
        time.sleep(1)
    return ["https://www.argentina.gob.ar" + h for h in out][:25]


NOMBRE = re.compile(r"CAPITALIZABLE EN PESOS CON VENCIMIENTO\s+(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚ]+\s+DE\s+\d{4})\s*\(\s*([ST]\d{2}[A-Z]\d)\s*-\s*(NUEVA|REAPERTURA)", re.I)


def leer_pagina(url, log):
    try:
        txt = texto(get(url))
    except Exception as e:
        log.append({"url": url, "error": str(e)})
        return []
    up = txt.upper()
    fecha_liq = None
    m = re.search(r"LIQUIDACI[ÓO]N[^0-9]{0,60}(\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2} DE [A-ZÁÉÍÓÚ]+ DE \d{4})", up)
    if m:
        try:
            fecha_liq = parse_fecha(m.group(1))
        except ValueError:
            pass
    found = []
    for m in NOMBRE.finditer(up):
        venc_s, t, tipo = m.group(1), m.group(2).upper(), m.group(3).upper()
        frag = txt[m.start():m.start() + 700]
        item = {"url": url, "t": t, "tipo": tipo, "venc_txt": venc_s, "texto": frag[:400]}
        try:
            item["venc"] = parse_fecha(venc_s).isoformat()
        except ValueError as e:
            item["error"] = str(e)
        # TEM con la que capitaliza: en reaperturas viene en la nota "capitaliza a una TEM de X% desde la fecha de emisión"
        n = re.search(re.escape(t) + r"[^.]{0,80}?capitaliza a una TEM de\s*(\d+(?:,\d+)?)\s*%", txt, re.I)
        if n:
            item["tem"] = float(n.group(1).replace(",", ".")) / 100
        elif tipo == "NUEVA":
            k = re.search(r"(\d+,\d+)\s*%", frag[len(m.group(0)):])
            if k:
                item["tem"] = float(k.group(1).replace(",", ".")) / 100
            if fecha_liq:
                item["emision"] = fecha_liq.isoformat()
        item["fam"] = "LECAP" if t.startswith("S") else "BONCAP"
        found.append(item)
    if not found:
        log.append({"url": url, "nota": "sin LECAP/BONCAP reconocibles"})
    return found


def precio_mercado():
    m = {}
    for ep in ("arg_notes", "arg_bonds"):
        try:
            for x in requests.get("https://data912.com/live/" + ep, timeout=30).json():
                if x.get("symbol") and x.get("c"):
                    m[x["symbol"]] = float(x["c"])
        except Exception as e:
            print("  data912", ep, e)
    return m


def automatico():
    rf = load()
    tengo = {x["t"] for x in rf["lecaps"]}
    log, cargados = [], []
    precios = precio_mercado()
    hoy = dt.date.today()
    for url in links_licitacion():
        for it in leer_pagina(url, log):
            if it["t"] in tengo:
                it["estado"] = "ya cargado"
            elif it.get("tipo") == "REAPERTURA":
                it["estado"] = "reapertura de una letra no cargada: falta la fecha de emisión original (cargar a mano)"
            elif not (it.get("venc") and it.get("tem") and it.get("emision")):
                it["estado"] = "datos incompletos: no se carga"
            else:
                em, ve = dt.date.fromisoformat(it["emision"]), dt.date.fromisoformat(it["venc"])
                vf = valor_final(em, ve, it["tem"])
                px = precios.get(it["t"])
                dias = (ve - hoy).days
                ok = 0.002 <= it["tem"] <= 0.08 and em < ve
                if px and dias > 0:
                    tem_mkt = (vf / px) ** (30 / dias) - 1
                    it["tem_mercado"] = round(tem_mkt, 5)
                    ok = ok and 0.002 <= tem_mkt <= 0.08
                if ok:
                    row = upsert(rf, it["t"], it["fam"], em, ve, it["tem"], "licitación (automático): " + url)
                    tengo.add(it["t"])
                    cargados.append(row)
                    it["estado"] = "cargado"
                else:
                    it["estado"] = "descartado por control de razonabilidad"
            log.append(it)
    # letras cargadas que ya vencieron: se sacan
    antes = len(rf["lecaps"])
    rf["lecaps"] = [x for x in rf["lecaps"] if x["venc"] >= hoy.isoformat()]
    vencidas = antes - len(rf["lecaps"])
    if cargados or vencidas:
        save(rf)
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump({"fecha": hoy.isoformat(), "cargados": cargados, "vencidas_quitadas": vencidas, "detalle": log},
                  f, ensure_ascii=False, indent=1)
    print(f"Cargadas {len(cargados)} letras nuevas · quitadas {vencidas} vencidas · {len(log)} registros en {LOG}")


if __name__ == "__main__":
    if not manual():
        automatico()
