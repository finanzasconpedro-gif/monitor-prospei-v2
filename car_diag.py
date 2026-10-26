"""Prueba única: ¿hay precios históricos desde el 1/1/2026 para armar el seguimiento de las carteras?
Guarda car_diag.json con lo que respondió cada fuente."""
import json, datetime as dt, requests

out = {"fecha": dt.date.today().isoformat(), "pruebas": []}

def probar(nombre, url):
    r = {"nombre": nombre, "url": url}
    try:
        x = requests.get(url, timeout=40, headers={"User-Agent": "Mozilla/5.0"})
        r["http"] = x.status_code
        try:
            j = x.json()
            if isinstance(j, list):
                r["n"] = len(j); r["primero"] = j[0] if j else None; r["ultimo"] = j[-1] if j else None
            else:
                r["json"] = str(j)[:600]
        except Exception:
            r["texto"] = x.text[:400]
    except Exception as e:
        r["error"] = str(e)
    out["pruebas"].append(r)

B = "https://data912.com/historical/"
for t in ["AL30D", "AL30", "GD30D", "AO27D"]:
    probar("bono " + t, B + "bonds/" + t)
for t in ["YMCXD", "YMCXO", "VSCVD", "TLCTD"]:
    probar("ON bonds/" + t, B + "bonds/" + t)
    probar("ON corp/" + t, B + "corp/" + t)
probar("cedear KO", B + "cedears/KO")
probar("accion GGAL", B + "stocks/GGAL")
A = "https://api.argentinadatos.com/v1/finanzas/fci/"
for f in ["2026/01/02", "2026/03/31"]:
    try:
        x = requests.get(A + "mercadoDinero/" + f, timeout=40).json()
        out["pruebas"].append({"nombre": "fci mercadoDinero " + f, "n": len(x) if isinstance(x, list) else None,
                               "balanz": [y for y in x if "balanz" in str(y.get("fondo", "")).lower()][:5] if isinstance(x, list) else str(x)[:300]})
    except Exception as e:
        out["pruebas"].append({"nombre": "fci " + f, "error": str(e)})
for tp in ["rentaFija", "otros", "rentaMixta"]:
    try:
        x = requests.get(A + tp + "/ultimo", timeout=40).json()
        out["pruebas"].append({"nombre": "fci " + tp + " ultimo (balanz)", "balanz": [y for y in x if "balanz" in str(y.get("fondo", "")).lower()][:40]})
    except Exception as e:
        out["pruebas"].append({"nombre": "fci " + tp, "error": str(e)})
try:
    import yfinance as yf
    h = yf.Ticker("GOVT").history(start="2026-01-01", auto_adjust=False)
    out["pruebas"].append({"nombre": "yahoo GOVT", "n": len(h), "primero": str(h.index[0]) if len(h) else None,
                           "dividendos": float(h["Dividends"].sum()) if len(h) else None})
except Exception as e:
    out["pruebas"].append({"nombre": "yahoo", "error": str(e)})
json.dump(out, open("car_diag.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
