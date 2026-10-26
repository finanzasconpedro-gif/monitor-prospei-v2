"""Prueba única: ¿están las cuotapartes de BCMMA, ESTRA1 y ESTRA3 en argentinadatos (CAFCI)?
Guarda car_diag.json con todos los fondos de Balanz de cada categoría y si hay datos en fechas pasadas."""
import json, datetime as dt, requests

A = "https://api.argentinadatos.com/v1/finanzas/fci/"
TIPOS = ["mercadoDinero", "rentaFija", "rentaMixta", "rentaVariable", "otros"]
out = {"fecha": dt.date.today().isoformat(), "ultimo": {}, "historia": {}}
for tp in TIPOS:
    try:
        x = requests.get(A + tp + "/ultimo", timeout=40).json()
        out["ultimo"][tp] = [{"fondo": y.get("fondo"), "fecha": y.get("fecha"), "vcp": y.get("vcp")}
                             for y in x if "balanz" in str(y.get("fondo", "")).lower()]
    except Exception as e:
        out["ultimo"][tp] = str(e)
# historia: cuántos fondos hay y si aparecen los de Balanz buscados en algunas fechas del año
BUSCA = ["money market", "corto plazo", "latam"]
for f in ["2026/01/02", "2026/01/05", "2026/01/15", "2026/02/02", "2026/03/02", "2026/06/01", "2026/09/01"]:
    for tp in TIPOS:
        try:
            x = requests.get(A + tp + "/" + f, timeout=40).json()
            if not isinstance(x, list):
                continue
            hit = [{"fondo": y.get("fondo"), "vcp": y.get("vcp")} for y in x
                   if "balanz" in str(y.get("fondo", "")).lower() and any(b in str(y.get("fondo", "")).lower() for b in BUSCA)]
            out["historia"].setdefault(f, {})[tp] = {"n_fondos": len(x), "balanz": hit}
        except Exception as e:
            out["historia"].setdefault(f, {})[tp] = str(e)
json.dump(out, open("car_diag.json", "w"), ensure_ascii=False, indent=1)
print("ok")
