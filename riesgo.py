"""Riesgo país (EMBI de JP Morgan para Argentina) desde varias fuentes públicas.
Guarda en riesgo.json el valor más reciente que encuentre, con su fecha y su fuente, y una historia corta.
Se corre varias veces por día desde GitHub Actions (riesgo.yml); la página usa el dato más nuevo entre
este archivo y el que consulta en vivo."""
import datetime as dt
import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json,text/plain,*/*"}
OUT = "riesgo.json"


def num(s):
    """'1.234,5' -> 1234.5 · '640' -> 640"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def argentinadatos():
    r = requests.get("https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais/ultimo", headers=UA, timeout=20)
    r.raise_for_status()
    j = r.json()
    return {"valor": num(j.get("valor")), "fecha": str(j.get("fecha"))[:10], "fuente": "ArgentinaDatos"}


def ambito():
    last = None
    for url in ("https://mercados.ambito.com//riesgopais/variacion", "https://mercados.ambito.com/riesgopais/variacion"):
        try:
            r = requests.get(url, headers={**UA, "Referer": "https://www.ambito.com/"}, timeout=20)
            r.raise_for_status()
            j = r.json()
            v = num(j.get("ultimo") or j.get("valor") or j.get("cierre"))
            f = str(j.get("fecha") or "")
            m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", f)
            if v and m:
                d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                return {"valor": v, "fecha": d.isoformat(), "fuente": "Ámbito", "hora": f}
            last = f"respuesta sin valor o fecha: {str(j)[:200]}"
        except Exception as e:
            last = str(e)
    raise RuntimeError(last)


def main():
    cands = []
    for name, fn in (("ArgentinaDatos", argentinadatos), ("Ámbito", ambito)):
        try:
            c = fn()
            if c["valor"] and 50 <= c["valor"] <= 20000:
                cands.append(c)
                print(f"{name}: {c['valor']:.0f} pb al {c['fecha']}")
            else:
                print(f"{name}: valor fuera de rango {c}")
        except Exception as e:
            print(f"{name}: sin dato ({e})")
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = {}
    if not cands:
        print("Ninguna fuente respondió: se conserva el dato anterior.")
        return
    best = max(cands, key=lambda c: (c["fecha"], c["fuente"] == "Ámbito"))
    hist = [h for h in old.get("hist", []) if h.get("fecha") != best["fecha"]]
    hist.append({"fecha": best["fecha"], "valor": best["valor"]})
    hist = sorted(hist, key=lambda h: h["fecha"])[-90:]
    out = {**best, "actualizado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "fuentes": cands, "hist": hist}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Guardado: {best['valor']:.0f} pb al {best['fecha']} ({best['fuente']})")


if __name__ == "__main__":
    main()
