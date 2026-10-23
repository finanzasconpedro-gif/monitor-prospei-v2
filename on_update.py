"""
Arma ons.json con las obligaciones negociables en dólares más operadas y su flujo de pagos (GitHub Actions, ons.yml).

1) Lista: las 80 ONs más operadas en Balanz (META, abajo) + las de más volumen en data912 (/live/arg_corp)
   que no estén en esa lista.
2) Flujo de pagos, emisor, ley, cupón, etc.: página de perfil de Rava (rava.com/perfil/<TICKER>).
3) Guarda ons.json (lo lee el monitor) y on_debug.json (qué se leyó de cada una y qué falló).

El monitor calcula TIR, duration y paridad en el navegador con el precio en vivo; acá sólo se guardan los datos fijos.
"""
import datetime as dt
import html as H
import json
import re
import sys
import time

import requests

N_EXTRA = 20          # además de la lista base, las ONs en MEP con más volumen en data912 que no estén en ella
# Lista base (Balanz, 23/10/2026, las 80 con más monto operado): ticker sin sufijo y datos de la ficha
META = [{"t": "YM44", "emp": "YPF", "ley": "NY", "mon": "CABLE", "calif": "B (S&P internacional)", "lam": "1.000", "cup": 7.55, "frec": "Semestral", "venc": "2035-06-17"},
 {"t": "YM43", "emp": "YPF", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 5.5, "frec": "Semestral", "venc": "2030-04-13"},
 {"t": "YM34", "emp": "YPF", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 8.25, "frec": "Semestral", "venc": "2034-01-16"},
 {"t": "PLC7", "emp": "Pluspetrol", "ley": "NY", "mon": "CABLE", "calif": "AAA (Fix SCR)", "lam": "1.000", "cup": 7.55, "frec": "Semestral", "venc": "2037-09-29"},
 {"t": "VSCV", "emp": "Vista", "ley": "NY", "mon": "CABLE", "calif": "BB- (Fitch)", "lam": "1.000", "cup": 8.5, "frec": "Semestral", "venc": "2033-06-09"},
 {"t": "TLCT", "emp": "Telecom", "ley": "NY", "mon": "CABLE", "calif": "B2 (Moodys)", "lam": "1", "cup": 8.5, "frec": "Semestral", "venc": "2036-01-19"},
 {"t": "YMCX", "emp": "YPF", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1", "cup": 8.75, "frec": "Semestral", "venc": "2031-09-10"},
 {"t": "VSCX", "emp": "Vista", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 7.88, "frec": "Semestral", "venc": "2038-04-07"},
 {"t": "PNXC", "emp": "PAE", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 8.5, "frec": "Semestral", "venc": "2032-04-29"},
 {"t": "DNCA", "emp": "Edenor", "ley": "NY", "mon": "CABLE", "calif": "A1(arg) (FIX)", "lam": "100", "cup": 9.5, "frec": "Semestral", "venc": "2033-04-28"},
 {"t": "TLCP", "emp": "Telecom", "ley": "NY", "mon": "CABLE", "calif": "B (Fitch)", "lam": "1", "cup": 9.25, "frec": "Semestral", "venc": "2033-05-27"},
 {"t": "YM38", "emp": "YPF", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 7.5, "frec": "Trimestral", "venc": "2027-07-21"},
 {"t": "VMC1", "emp": "VMOS", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) Fix", "lam": "1", "cup": 6.25, "frec": "Trimestral", "venc": "2030-09-21"},
 {"t": "PLC4", "emp": "Pluspetrol", "ley": "NY", "mon": "CABLE", "calif": "BB (Fitch)", "lam": "1.000", "cup": 8.5, "frec": "Semestral", "venc": "2032-05-29"},
 {"t": "TTCD", "emp": "Tecpetrol", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 7.63, "frec": "Semestral", "venc": "2030-11-02"},
 {"t": "IRCP", "emp": "IRSA", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1", "cup": 8.0, "frec": "Semestral", "venc": "2035-03-30"},
 {"t": "YM42", "emp": "YPF", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 7.0, "frec": "Semestral", "venc": "2029-03-01"},
 {"t": "YMCY", "emp": "YPF", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 6.5, "frec": "Trimestral", "venc": "2028-10-09"},
 {"t": "BACG", "emp": "Banco Macro", "ley": "NY", "mon": "CABLE", "calif": "CCC+ (Fitch)", "lam": "1.000", "cup": 8.0, "frec": "Semestral", "venc": "2029-06-22"},
 {"t": "TLCM", "emp": "Telecom", "ley": "NY", "mon": "CABLE", "calif": "AA+(arg)", "lam": "1.000", "cup": 9.5, "frec": "Semestral", "venc": "2031-07-17"},
 {"t": "YM37", "emp": "YPF", "ley": "ARG", "mon": "MEP", "calif": "AAA (FIX)", "lam": "100", "cup": 7.0, "frec": "Trimestral", "venc": "2027-05-06"},
 {"t": "PN36", "emp": "PAE", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "50", "cup": 7.25, "frec": "Semestral", "venc": "2031-11-12"},
 {"t": "MCC3", "emp": "Pecom", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2030-05-10"},
 {"t": "OLC7", "emp": "Oleoductos Del Valle", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 6.9, "frec": "Semestral", "venc": "2030-02-22"},
 {"t": "PLC5", "emp": "Pluspetrol", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 8.13, "frec": "Semestral", "venc": "2031-05-17"},
 {"t": "PN35", "emp": "PAE", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 7.0, "frec": "Semestral", "venc": "2029-09-26"},
 {"t": "RUCE", "emp": "Msu Energy", "ley": "ARG", "mon": "MEP", "calif": "AA-(arg) (FIX)", "lam": "100", "cup": 7.5, "frec": "Trimestral", "venc": "2027-10-29"},
 {"t": "MGCR", "emp": "Pampa", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "10.000", "cup": 7.75, "frec": "Semestral", "venc": "2037-11-13"},
 {"t": "MGCO", "emp": "Pampa", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "10.000", "cup": 7.88, "frec": "Semestral", "venc": "2034-12-15"},
 {"t": "DNC7", "emp": "Edenor", "ley": "NY", "mon": "CABLE", "calif": "CCC+ (Fitch)", "lam": "100", "cup": 9.75, "frec": "Semestral", "venc": "2030-10-23"},
 {"t": "RC1C", "emp": "Arcor", "ley": "NY", "mon": "CABLE", "calif": "B+ (Fitch)", "lam": "1.000", "cup": 7.6, "frec": "Semestral", "venc": "2033-07-30"},
 {"t": "TSC4", "emp": "TGS", "ley": "NY", "mon": "CABLE", "calif": "B (Fitch)", "lam": "1.000", "cup": 7.75, "frec": "Semestral", "venc": "2035-11-19"},
 {"t": "YM39", "emp": "YPF", "ley": "ARG", "mon": "CABLE", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 8.75, "frec": "Semestral", "venc": "2030-07-21"},
 {"t": "VSCR", "emp": "Vista", "ley": "ARG", "mon": "CABLE", "calif": "AAA (FIX)", "lam": "1", "cup": 7.65, "frec": "Semestral", "venc": "2031-10-09"},
 {"t": "OLC6", "emp": "Oleoductos Del Valle", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2029-06-04"},
 {"t": "HJCJ", "emp": "John Deere Credit", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1.000", "cup": 8.5, "frec": "Semestral", "venc": "2027-07-24"},
 {"t": "RCCR", "emp": "Arcor", "ley": "ARG", "mon": "MEP", "calif": "AAA (FIX)", "lam": "100", "cup": 6.75, "frec": "Semestral", "venc": "2027-05-08"},
 {"t": "PLC2", "emp": "Pluspetrol", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2030-01-26"},
 {"t": "PFC3", "emp": "Profertil", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 5.75, "frec": "Semestral", "venc": "2029-11-07"},
 {"t": "PN38", "emp": "PAE", "ley": "ARG", "mon": "CABLE", "calif": "-", "lam": "50", "cup": 6.5, "frec": "Semestral", "venc": "2027-08-10"},
 {"t": "TSC3", "emp": "TGS", "ley": "NY", "mon": "CABLE", "calif": "B (Fitch)", "lam": "10.000", "cup": 8.5, "frec": "Semestral", "venc": "2031-07-23"},
 {"t": "LOC5", "emp": "Loma Negra", "ley": "ARG", "mon": "MEP", "calif": "AAA (FIX)", "lam": "50", "cup": 8.0, "frec": "Semestral", "venc": "2027-07-22"},
 {"t": "BYCH", "emp": "Banco Galicia", "ley": "NY", "mon": "CABLE", "calif": "A1+(arg)", "lam": "2.000", "cup": 7.75, "frec": "Semestral", "venc": "2028-10-09"},
 {"t": "MGCT", "emp": "Pampa", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1.000", "cup": 5.49, "frec": "Semestral", "venc": "2029-03-31"},
 {"t": "SBC2", "emp": "Scania Credit", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1", "cup": 7.49, "frec": "Trimestral", "venc": "2029-01-15"},
 {"t": "YM40", "emp": "YPF", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 7.5, "frec": "Trimestral", "venc": "2028-08-27"},
 {"t": "YMCJ", "emp": "YPF", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1", "cup": 7.0, "frec": "Semestral", "venc": "2033-09-29"},
 {"t": "TTC9", "emp": "Tecpetrol", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 6.8, "frec": "Semestral", "venc": "2029-10-23"},
 {"t": "MGCM", "emp": "Pampa", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "10.000", "cup": 7.95, "frec": "Semestral", "venc": "2031-09-09"},
 {"t": "DNC3", "emp": "Edenor", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 9.75, "frec": "Semestral", "venc": "2026-11-21"},
 {"t": "DNCB", "emp": "Edenor", "ley": "ARG", "mon": "CABLE", "calif": "—", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2029-07-02"},
 {"t": "EAC4", "emp": "Msu Green", "ley": "NY", "mon": "CABLE", "calif": "—", "lam": "1", "cup": 9.75, "frec": "Semestral", "venc": "2036-06-15"},
 {"t": "DNC5", "emp": "Edenor", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 9.5, "frec": "Semestral", "venc": "2028-08-04"},
 {"t": "ARC1", "emp": "AA2000", "ley": "NY", "mon": "CABLE", "calif": "AA(arg)", "lam": "1.000", "cup": 8.5, "frec": "Trimestral", "venc": "2031-07-31"},
 {"t": "SBC3", "emp": "Scania Credit", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 6.5, "frec": "Trimestral", "venc": "2029-05-25"},
 {"t": "CP38", "emp": "CGC", "ley": "NY", "mon": "CABLE", "calif": "AA-(arg) (FIX)", "lam": "100", "cup": 11.88, "frec": "Semestral", "venc": "2030-11-27"},
 {"t": "VSCU", "emp": "Vista", "ley": "ARG", "mon": "CABLE", "calif": "AAA (FIX)", "lam": "1.000", "cup": 7.5, "frec": "Semestral", "venc": "2030-03-06"},
 {"t": "VSCT", "emp": "Vista", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "10.000", "cup": 7.63, "frec": "Semestral", "venc": "2035-12-09"},
 {"t": "MGCQ", "emp": "Pampa", "ley": "ARG", "mon": "CABLE", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 7.25, "frec": "Semestral", "venc": "2028-08-05"},
 {"t": "OZC3", "emp": "EDEMSA", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2027-11-28"},
 {"t": "XMC1", "emp": "Minera Exar", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2027-11-10"},
 {"t": "TLCO", "emp": "Telecom", "ley": "ARG", "mon": "MEP", "calif": "AA+ (FIX)", "lam": "100", "cup": 7.0, "frec": "Semestral", "venc": "2028-11-27"},
 {"t": "CS47", "emp": "Cresud", "ley": "ARG", "mon": "MEP", "calif": "AA+(arg) (FIX)", "lam": "100", "cup": 7.0, "frec": "Semestral", "venc": "2028-11-14"},
 {"t": "AFCI", "emp": "Banco Comafi", "ley": "ARG", "mon": "MEP", "calif": "A1+ (FIX)", "lam": "1", "cup": 6.5, "frec": "Semestral", "venc": "2026-11-06"},
 {"t": "CAC5", "emp": "Capex", "ley": "NY", "mon": "CABLE", "calif": "AA (arg)", "lam": "1", "cup": 9.25, "frec": "Semestral", "venc": "2028-08-24"},
 {"t": "BACH", "emp": "Banco Macro", "ley": "NY", "mon": "CABLE", "calif": "—", "lam": "1.000", "cup": 8.0, "frec": "Semestral", "venc": "2031-01-27"},
 {"t": "RUCD", "emp": "Msu Energy", "ley": "NY", "mon": "CABLE", "calif": "CCC (Fitch)", "lam": "1", "cup": 9.75, "frec": "Semestral", "venc": "2030-12-04"},
 {"t": "PLC6", "emp": "Pluspetrol", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 6.5, "frec": "Semestral", "venc": "2029-02-26"},
 {"t": "LDCG", "emp": "Ledesma", "ley": "ARG", "mon": "MEP", "calif": "AA- (FIX)", "lam": "100", "cup": 7.0, "frec": "Trimestral", "venc": "2027-10-03"},
 {"t": "LOC6", "emp": "Loma Negra", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "50", "cup": 6.5, "frec": "Semestral", "venc": "2029-01-22"},
 {"t": "IRCO", "emp": "IRSA", "ley": "ARG", "mon": "MEP", "calif": "AA+ (FIX)", "lam": "1", "cup": 7.25, "frec": "Semestral", "venc": "2029-10-22"},
 {"t": "OT42", "emp": "Oiltanking", "ley": "ARG", "mon": "MEP", "calif": "AA.ar (Moodys)", "lam": "100", "cup": 8.0, "frec": "Trimestral", "venc": "2030-01-16"},
 {"t": "MTC2", "emp": "Mastellone", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 6.5, "frec": "Trimestral", "venc": "2028-06-21"},
 {"t": "TTCA", "emp": "Tecpetrol", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 7.63, "frec": "Semestral", "venc": "2033-01-21"},
 {"t": "PN43", "emp": "PAE", "ley": "NY", "mon": "CABLE", "calif": "-", "lam": "1.000", "cup": 7.75, "frec": "Semestral", "venc": "2037-01-14"},
 {"t": "PQCS", "emp": "Petroquimica Comodoro Rivadavia", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "50", "cup": 8.0, "frec": "Semestral", "venc": "2031-02-16"},
 {"t": "TTCE", "emp": "Tecpetrol", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 5.5, "frec": "Semestral", "venc": "2029-05-20"},
 {"t": "NPCC", "emp": "Central Puerto", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2029-08-24"},
 {"t": "YMCI", "emp": "YPF", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1", "cup": 9.0, "frec": "Semestral", "venc": "2029-06-29"},
 {"t": "CP41", "emp": "CGC", "ley": "ARG", "mon": "MEP", "calif": "AA-(arg) (FIX)", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2029-09-06"}]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "es-AR,es;q=0.9"}
HOY = dt.date.today()


def num(s):
    s = str(s).strip().replace("$", "").replace("%", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def fecha(s):
    s = s.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise ValueError(s)


def lista():
    L = []
    try:
        r = requests.get("https://data912.com/live/arg_corp", timeout=40)
        r.raise_for_status()
        L = r.json()
    except Exception as e:
        print("data912 no disponible:", e)
    base = [m["t"] for m in META]
    d = [x for x in L if str(x.get("symbol", "")).endswith("D") and (x.get("c") or 0) > 0 and x["symbol"][:-1] not in base]
    d.sort(key=lambda x: -(x.get("v") or 0))
    extra = [x["symbol"][:-1] for x in d[:N_EXTRA]]
    return base + extra, {x["symbol"]: x for x in L}


def texto(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", H.unescape(h))


def json_embebido(h):
    """Rava suele mandar los datos del perfil como JSON dentro de un atributo (:res='{...}') o en un <script>."""
    blobs = []
    for m in re.finditer(r""":?[a-z\-]+=(["'])(\{.{200,}?\})\1""", h, re.S):
        blobs.append(H.unescape(m.group(2)))
    for m in re.finditer(r"(?s)<script[^>]*>(.*?)</script>", h):
        s = m.group(1)
        if "flujo" in s.lower():
            blobs.append(s)
    out = []
    for b in blobs:
        try:
            out.append(json.loads(b))
        except Exception:
            k = b.find("{")
            try:
                out.append(json.loads(b[k:b.rfind("}") + 1]))
            except Exception:
                pass
    return out


def buscar_clave(o, pred, path=""):
    """Recorre un JSON y devuelve (ruta, valor) de los nodos que cumplen pred."""
    if pred(path, o):
        yield path, o
    if isinstance(o, dict):
        for k, v in o.items():
            yield from buscar_clave(v, pred, path + "/" + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o[:3] if len(o) > 200 else o):
            yield from buscar_clave(v, pred, path + f"[{i}]")


def flujo_de_json(objs):
    """Busca una lista de pagos con fecha + interés/renta + amortización."""
    for o in objs:
        for path, v in buscar_clave(o, lambda p, x: isinstance(x, list) and len(x) > 0 and isinstance(x[0], dict)
                                    and any("fecha" in k.lower() for k in x[0])
                                    and any(("renta" in k.lower() or "inter" in k.lower() or "cupon" in k.lower()) for k in x[0])):
            k0 = v[0]
            kf = next(k for k in k0 if "fecha" in k.lower())
            ki = next(k for k in k0 if "renta" in k.lower() or "inter" in k.lower() or "cupon" in k.lower())
            ka = next((k for k in k0 if "amort" in k.lower()), None)
            ks = next((k for k in k0 if "saldo" in k.lower() or "residual" in k.lower()), None)
            rows = []
            for r in v:
                try:
                    rows.append([fecha(str(r[kf])).isoformat(), num(r[ki]), num(r[ka]) if ka else 0.0,
                                 num(r[ks]) if ks else None])
                except Exception:
                    pass
            if rows:
                return rows, path, list(k0.keys())
    return None, None, None


def flujo_de_texto(t):
    i = t.lower().find("flujo de fondos")
    seg = t[i:] if i >= 0 else t
    rows = []
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})\s+([\d.]*\d,\d+|\d+(?:\.\d+)?)\s+([\d.]*\d,\d+|\d+(?:\.\d+)?)\s+([\d.]*\d,\d+|\d+(?:\.\d+)?)\s+([\d.]*\d,\d+|\d+(?:\.\d+)?)", seg):
        try:
            rows.append([fecha(m.group(1)).isoformat(), num(m.group(2)), num(m.group(3)), num(m.group(5))])
        except Exception:
            pass
    return rows


def campo(t, etiqueta, largo=60):
    m = re.search(etiqueta + r"\s*:?\s*(.{1,%d}?)(?=\s{2,}|$| [A-ZÁÉÍÓÚ][a-záéíóú]+\s*:)" % largo, t)
    return m.group(1).strip() if m else None


def perfil(base):
    for t in (base + "D", base + "O", base + "C"):
        url = "https://www.rava.com/perfil/" + t
        r = requests.get(url, headers=UA, timeout=40)
        if r.status_code == 200 and "Flujo" in r.text:
            break
    info = {"t": t, "http": r.status_code, "bytes": len(r.text)}
    if r.status_code != 200:
        return info, None
    h = r.text
    tx = texto(h)
    objs = json_embebido(h)
    rows, path, keys = flujo_de_json(objs)
    info["fuente_flujo"] = "json " + str(path) if rows else None
    if rows:
        info["claves_flujo"] = keys
    else:
        rows = flujo_de_texto(tx)
        info["fuente_flujo"] = "texto" if rows else "no encontrado"
    # muestras para diagnosticar
    for pat in ("Flujo de fondos", "flujo", "Ley", "Cup", "Emisor", "Amortiz"):
        k = h.find(pat)
        if k >= 0:
            info["html_" + pat[:6]] = h[max(0, k - 150):k + 450]
            break
    k = tx.find("Flujo de fondos")
    info["texto_flujo"] = tx[max(0, k - 800):k + 600] if k >= 0 else tx[:1500]
    info["n_json"] = len(objs)
    if objs:
        info["json_claves"] = [list(o.keys())[:40] if isinstance(o, dict) else type(o).__name__ for o in objs[:5]]
    if not rows:
        return info, None
    rows = [x for x in rows if x[0] > HOY.isoformat()]
    rows.sort()
    # capital vivo antes de cada pago = suma de las amortizaciones que faltan (no depende de cómo lo informe la fuente)
    for i in range(len(rows)):
        rows[i][3] = round(sum(r[2] for r in rows[i:]), 6)
    nombre = None
    m = re.search(r"<title>(.*?)</title>", h, re.S)
    if m:
        nombre = H.unescape(m.group(1)).strip()
    tir = re.search(r"TIR\s*:?\s*(-?\d+,\d+)\s*%", tx)
    dur = re.search(r"Duration[^0-9]{0,30}(\d+,\d+)", tx, re.I)
    ley = re.search(r"\bLey\s*:?\s*(Nueva York|NY|Argentina|ARG|Arg\w*|Extranjera|Local)", tx, re.I)
    on = {"t": base, "rava": t, "nombre": nombre, "texto_ficha": None,
          "ley": ley.group(1) if ley else None,
          "tir_rava": num(tir.group(1)) if tir else None,
          "dur_rava": num(dur.group(1)) if dur else None,
          "flows": rows}
    k = tx.find("Flujo de fondos")
    on["texto_ficha"] = tx[max(0, k - 900):k][:900] if k >= 0 else None
    return info, on


def main():
    tickers, px = lista()
    print(len(tickers), "ONs a buscar")
    ons, debug = [], []
    for i, t in enumerate(tickers):
        try:
            info, on = perfil(t)
        except Exception as e:
            info, on = {"t": t, "error": str(e)}, None
        if i >= 4:   # el detalle crudo sólo para las primeras, para no inflar el archivo
            for k in list(info):
                if k.startswith("html_") or k == "texto_flujo":
                    info.pop(k)
        debug.append(info)
        if on and on["flows"]:
            m = next((m for m in META if m["t"] == t), {})
            on.update({k: v for k, v in m.items() if k != "t"})
            on["v"] = (px.get(t + "D") or {}).get("v")
            ons.append(on)
        print(t, info.get("http"), info.get("fuente_flujo"), len(on["flows"]) if on else 0)
        time.sleep(1.2)
    with open("ons.json", "w", encoding="utf-8") as f:
        json.dump({"updated": HOY.isoformat(), "ons": ons}, f, ensure_ascii=False, separators=(",", ":"))
    with open("on_debug.json", "w", encoding="utf-8") as f:
        json.dump(debug, f, ensure_ascii=False, indent=1)
    print("Guardadas", len(ons), "ONs con flujo")


if __name__ == "__main__":
    main()
