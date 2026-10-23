"""
Arma ons.json con las obligaciones negociables en dólares más operadas y su flujo de pagos (GitHub Actions, ons.yml).

1) Lista: las 205 ONs en dólares de Balanz (META, abajo) + las de más volumen en data912 (/live/arg_corp)
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
# Lista base: las 205 ONs en dólares del monitor de Balanz (23/10/2026), ordenadas por monto operado: ticker sin sufijo y datos de la ficha
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
 {"t": "MCC3", "emp": "PECOM", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2030-05-10"},
 {"t": "OLC7", "emp": "Oleoductos Del Valle", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 6.9, "frec": "Semestral", "venc": "2030-02-22"},
 {"t": "PLC5", "emp": "Pluspetrol", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 8.13, "frec": "Semestral", "venc": "2031-05-17"},
 {"t": "PN35", "emp": "PAE", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 7.0, "frec": "Semestral", "venc": "2029-09-26"},
 {"t": "RUCE", "emp": "MSU ENERGY", "ley": "ARG", "mon": "MEP", "calif": "AA-(arg) (FIX)", "lam": "100", "cup": 7.5, "frec": "Trimestral", "venc": "2027-10-29"},
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
 {"t": "EAC4", "emp": "MSU GREEN", "ley": "NY", "mon": "CABLE", "calif": "—", "lam": "1", "cup": 9.75, "frec": "Semestral", "venc": "2036-06-15"},
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
 {"t": "RUCD", "emp": "MSU ENERGY", "ley": "NY", "mon": "CABLE", "calif": "CCC (Fitch)", "lam": "1", "cup": 9.75, "frec": "Semestral", "venc": "2030-12-04"},
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
 {"t": "CP41", "emp": "CGC", "ley": "ARG", "mon": "MEP", "calif": "AA-(arg) (FIX)", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2029-09-06"},
 {"t": "ZZC1", "emp": "Camuzzi", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.95, "frec": "Semestral", "venc": "2027-02-20"},
 {"t": "OZC8", "emp": "EDEMSA", "ley": "NY", "mon": "CABLE", "calif": "—", "lam": "10.000", "cup": 9.75, "frec": "Semestral", "venc": "2033-06-10"},
 {"t": "BYCW", "emp": "Banco Galicia", "ley": "ARG", "mon": "MEP", "calif": "ML A-1.ar (Moodys)", "lam": "1", "cup": 6.0, "frec": "Semestral", "venc": "2026-11-29"},
 {"t": "PN41", "emp": "PAE", "ley": "ARG", "mon": "CABLE", "calif": "AAA(arg) (FIX)", "lam": "50", "cup": 7.5, "frec": "Semestral", "venc": "2029-08-26"},
 {"t": "PLC3", "emp": "Pluspetrol", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.25, "frec": "Semestral", "venc": "2028-04-29"},
 {"t": "JNC6", "emp": "Inversora Juramento", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 9.0, "frec": "Semestral", "venc": "2027-10-02"},
 {"t": "LMS8", "emp": "Aluar", "ley": "ARG", "mon": "CABLE", "calif": "AAA (arg) (FIX)", "lam": "50", "cup": 6.25, "frec": "Trimestral", "venc": "2027-03-20"},
 {"t": "MIC4", "emp": "Mirgor", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 8.25, "frec": "Trimestral", "venc": "2027-07-28"},
 {"t": "CACB", "emp": "Capex", "ley": "ARG", "mon": "MEP", "calif": "AA (FIX)", "lam": "1", "cup": 7.75, "frec": "Trimestral", "venc": "2028-06-16"},
 {"t": "HJCL", "emp": "John Deere Credit", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1.000", "cup": 6.5, "frec": "Semestral", "venc": "2028-12-07"},
 {"t": "CS50", "emp": "Cresud", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 7.25, "frec": "Semestral", "venc": "2029-03-09"},
 {"t": "T641", "emp": "Tarjeta Naranja", "ley": "ARG", "mon": "MEP", "calif": "AA (FIX)", "lam": "1.200", "cup": 7.9, "frec": "Trimestral", "venc": "2027-04-29"},
 {"t": "MR46", "emp": "Gemsa", "ley": "NY", "mon": "CABLE", "calif": "—", "lam": "1.000", "cup": 7.0, "frec": "Semestral", "venc": "2034-12-30"},
 {"t": "NPCD", "emp": "Central Puerto", "ley": "ARG", "mon": "MEP", "calif": "AAA.ar (Moodys)", "lam": "100", "cup": 6.0, "frec": "Semestral", "venc": "2030-04-29"},
 {"t": "CACD", "emp": "Capex", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1", "cup": 8.25, "frec": "Semestral", "venc": "2029-06-03"},
 {"t": "CS53", "emp": "Cresud", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 6.25, "frec": "Semestral", "venc": "2030-04-29"},
 {"t": "LUC5", "emp": "Luz De Tres Picos", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2029-02-25"},
 {"t": "YFCJ", "emp": "Ypf Electrica", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 7.88, "frec": "Semestral", "venc": "2032-10-15"},
 {"t": "VSCZ", "emp": "Vista", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 5.0, "frec": "Semestral", "venc": "2029-07-15"},
 {"t": "RC5C", "emp": "Arcor", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 5.25, "frec": "Semestral", "venc": "2029-05-20"},
 {"t": "GN49", "emp": "Genneia", "ley": "NY", "mon": "CABLE", "calif": "B2 (Moodys)", "lam": "1.000", "cup": 7.75, "frec": "Semestral", "venc": "2033-12-01"},
 {"t": "VSCP", "emp": "Vista", "ley": "ARG", "mon": "CABLE", "calif": "AAA (FIX)", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2029-05-02"},
 {"t": "MCC2", "emp": "PECOM", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2027-06-01"},
 {"t": "HJCK", "emp": "John Deere Credit", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1.000", "cup": 7.75, "frec": "Semestral", "venc": "2029-01-15"},
 {"t": "IRCF", "emp": "IRSA", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1", "cup": 8.75, "frec": "Semestral", "venc": "2028-06-21"},
 {"t": "CS48", "emp": "Cresud", "ley": "ARG", "mon": "MEP", "calif": "AAA (FIX)", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2028-07-10"},
 {"t": "MCC1", "emp": "PECOM", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.9, "frec": "Semestral", "venc": "2029-03-09"},
 {"t": "MGCN", "emp": "Pampa", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 5.75, "frec": "Semestral", "venc": "2028-10-03"},
 {"t": "WBS3", "emp": "Banco Mariva", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "1.000", "cup": 6.0, "frec": "Trimestral", "venc": "2027-07-05"},
 {"t": "CICA", "emp": "Cnh", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "100", "cup": 8.0, "frec": "Semestral", "venc": "2028-06-02"},
 {"t": "HJCI", "emp": "John Deere Credit", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1.200", "cup": 7.5, "frec": "Semestral", "venc": "2027-05-26"},
 {"t": "YM41", "emp": "YPF", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 6.0, "frec": "Trimestral", "venc": "2027-01-07"},
 {"t": "YFCP", "emp": "Ypf Electrica", "ley": "ARG", "mon": "MEP", "calif": "AAA.ar (Moodys)", "lam": "1", "cup": 5.0, "frec": "Semestral", "venc": "2029-08-17"},
 {"t": "OTS7", "emp": "Oiltanking", "ley": "ARG", "mon": "MEP", "calif": "AAA.ar (Moodys)", "lam": "1", "cup": 6.25, "frec": "Trimestral", "venc": "2030-09-24"},
 {"t": "VSCY", "emp": "Vista", "ley": "ARG", "mon": "CABLE", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 3.75, "frec": "Semestral", "venc": "2028-01-15"},
 {"t": "SIC2", "emp": "Sidersa", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2029-06-18"},
 {"t": "OTS6", "emp": "Otamerica", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 6.74, "frec": "Trimestral", "venc": "2029-07-28"},
 {"t": "MIC3", "emp": "Mirgor", "ley": "ARG", "mon": "MEP", "calif": "ML A-1.ar", "lam": "100", "cup": 8.5, "frec": "Trimestral", "venc": "2026-11-10"},
 {"t": "CICB", "emp": "Cnh", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1", "cup": 7.5, "frec": "Semestral", "venc": "2029-02-08"},
 {"t": "MIC6", "emp": "Mirgor", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 8.0, "frec": "Trimestral", "venc": "2028-05-27"},
 {"t": "TTCB", "emp": "Tecpetrol", "ley": "ARG", "mon": "MEP", "calif": "AAA (FIX)", "lam": "1", "cup": 6.5, "frec": "Semestral", "venc": "2027-10-15"},
 {"t": "PN34", "emp": "PAE", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 4.97, "frec": "Semestral", "venc": "2027-09-26"},
 {"t": "YCAM", "emp": "YPF", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "10.000", "cup": 6.95, "frec": "Semestral", "venc": "2027-07-20"},
 {"t": "TLCU", "emp": "Telecom", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 6.5, "frec": "Semestral", "venc": "2029-03-04"},
 {"t": "OTS3", "emp": "Oiltanking", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 7.0, "frec": "Trimestral", "venc": "2028-10-31"},
 {"t": "TLCQ", "emp": "Telecom", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.5, "frec": "Trimestral", "venc": "2027-07-01"},
 {"t": "IRCJ", "emp": "IRSA", "ley": "ARG", "mon": "MEP", "calif": "AA+ (FIX)", "lam": "100", "cup": 7.0, "frec": "Semestral", "venc": "2027-02-27"},
 {"t": "BGC4", "emp": "Banco Patagonia", "ley": "ARG", "mon": "MEP", "calif": "A1 (FIX)", "lam": "1.200", "cup": 6.25, "frec": "Semestral", "venc": "2026-11-12"},
 {"t": "SNEB", "emp": "San Miguel", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "1", "cup": 8.0, "frec": "Semestral", "venc": "2029-07-13"},
 {"t": "OLC5", "emp": "Oleoductos Del Valle", "ley": "ARG", "mon": "MEP", "calif": "AAA (FIX)", "lam": "100", "cup": 7.89, "frec": "Semestral", "venc": "2028-06-11"},
 {"t": "TLCV", "emp": "Telecom", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 3.5, "frec": "Trimestral", "venc": "2027-05-28"},
 {"t": "EMC1", "emp": "Mega", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2027-07-03"},
 {"t": "EAC3", "emp": "MSU GREEN", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 8.5, "frec": "Semestral", "venc": "2028-12-19"},
 {"t": "SNSD", "emp": "San Miguel", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "50", "cup": 9.5, "frec": "Semestral", "venc": "2027-02-05"},
 {"t": "PLC1", "emp": "Pluspetrol", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 6.0, "frec": "Semestral", "venc": "2028-01-26"},
 {"t": "YFCG", "emp": "Ypf Electrica", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 5.0, "frec": "Trimestral", "venc": "2027-02-26"},
 {"t": "OT41", "emp": "Oiltanking", "ley": "ARG", "mon": "MEP", "calif": "AA.ar (Moodys)", "lam": "100", "cup": 7.0, "frec": "Trimestral", "venc": "2028-01-16"},
 {"t": "CP37", "emp": "CGC", "ley": "ARG", "mon": "MEP", "calif": "AA- (Moodys)", "lam": "1", "cup": 7.0, "frec": "Trimestral", "venc": "2027-03-09"},
 {"t": "OTS2", "emp": "Oiltanking", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 7.0, "frec": "Trimestral", "venc": "2027-04-23"},
 {"t": "GN47", "emp": "Genneia", "ley": "ARG", "mon": "MEP", "calif": "AA (FIX)", "lam": "1", "cup": 6.0, "frec": "Semestral", "venc": "2028-10-16"},
 {"t": "RZAB", "emp": "Rizobacter", "ley": "ARG", "mon": "MEP", "calif": "A+ (FIX)", "lam": "100", "cup": 8.0, "frec": "Trimestral", "venc": "2027-11-27"},
 {"t": "YFCI", "emp": "Ypf Electrica", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 5.9, "frec": "Trimestral", "venc": "2027-06-12"},
 {"t": "SBC1", "emp": "Scania Credit", "ley": "ARG", "mon": "MEP", "calif": "AA (FIX)", "lam": "100", "cup": 8.75, "frec": "Trimestral", "venc": "2027-09-04"},
 {"t": "YFCM", "emp": "Ypf Electrica", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 6.5, "frec": "Trimestral", "venc": "2027-05-19"},
 {"t": "YFCK", "emp": "Ypf Electrica", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 5.25, "frec": "Trimestral", "venc": "2026-11-21"},
 {"t": "CP40", "emp": "CGC", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 9.5, "frec": "Trimestral", "venc": "2028-03-08"},
 {"t": "YFCL", "emp": "Ypf Electrica", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "100", "cup": 6.75, "frec": "Trimestral", "venc": "2028-11-21"},
 {"t": "PECN", "emp": "Petrolera Aconcagua", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 3.0, "frec": "Anual", "venc": "2032-08-24"},
 {"t": "PQCR", "emp": "Petroquimica Comodoro Rivadavia", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1", "cup": 6.75, "frec": "Semestral", "venc": "2028-10-21"},
 {"t": "LMS7", "emp": "Aluar", "ley": "ARG", "mon": "CABLE", "calif": "AAA (arg) (FIX)", "lam": "1", "cup": 7.0, "frec": "Trimestral", "venc": "2028-10-11"},
 {"t": "FO4A", "emp": "Fyo", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 7.9, "frec": "Trimestral", "venc": "2027-07-19"},
 {"t": "CIC7", "emp": "Cnh", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 6.0, "frec": "Semestral", "venc": "2026-11-11"},
 {"t": "GN48", "emp": "Genneia", "ley": "ARG", "mon": "MEP", "calif": "AA+ (FIX)", "lam": "1", "cup": 6.5, "frec": "Semestral", "venc": "2028-03-04"},
 {"t": "TTC8", "emp": "Tecpetrol", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 5.0, "frec": "Semestral", "venc": "2027-10-23"},
 {"t": "CS52", "emp": "Cresud", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 4.75, "frec": "Semestral", "venc": "2028-04-29"},
 {"t": "HJCH", "emp": "John Deere Credit", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1.200", "cup": 7.0, "frec": "Semestral", "venc": "2028-01-16"},
 {"t": "HJCG", "emp": "John Deere Credit", "ley": "ARG", "mon": "MEP", "calif": "AA (FIX)", "lam": "1", "cup": 6.5, "frec": "Semestral", "venc": "2028-10-20"},
 {"t": "PFC2", "emp": "Profertil", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.25, "frec": "Semestral", "venc": "2027-07-13"},
 {"t": "AERB", "emp": "AA2000", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 5.5, "frec": "Semestral", "venc": "2026-12-14"},
 {"t": "GYC4", "emp": "360 Energy", "ley": "ARG", "mon": "MEP", "calif": "BV1(arg) (FIX)", "lam": "1", "cup": 8.0, "frec": "Trimestral", "venc": "2027-10-29"},
 {"t": "ZPC5", "emp": "Plaza Logistica", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 6.5, "frec": "Trimestral", "venc": "2029-06-25"},
 {"t": "PNDC", "emp": "PAE", "ley": "NY", "mon": "CABLE", "calif": "AAA(arg)", "lam": "1.000", "cup": 9.13, "frec": "Semestral", "venc": "2027-04-29"},
 {"t": "MR47", "emp": "Gemsa", "ley": "NY", "mon": "CABLE", "calif": "—", "lam": "1.000", "cup": 10.5, "frec": "Semestral", "venc": "2036-06-29"},
 {"t": "TLCW", "emp": "Telecom", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 6.25, "frec": "Semestral", "venc": "2030-05-28"},
 {"t": "IRCN", "emp": "IRSA", "ley": "ARG", "mon": "MEP", "calif": "AA+ (FIX)", "lam": "1", "cup": 5.75, "frec": "Semestral", "venc": "2027-10-22"},
 {"t": "CIC8", "emp": "Cnh", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2028-11-11"},
 {"t": "CP36", "emp": "CGC", "ley": "ARG", "mon": "MEP", "calif": "AA- (FIX)", "lam": "1", "cup": 6.5, "frec": "Semestral", "venc": "2027-10-09"},
 {"t": "PFC4", "emp": "Profertil", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) Fix", "lam": "1", "cup": 5.5, "frec": "Semestral", "venc": "2030-02-27"},
 {"t": "MSSG", "emp": "MSU ENERGY", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "1", "cup": 8.5, "frec": "Semestral", "venc": "2029-04-15"},
 {"t": "PN42", "emp": "PAE", "ley": "ARG", "mon": "MEP", "calif": "AAA(arg) (FIX)", "lam": "50", "cup": 6.0, "frec": "Semestral", "venc": "2027-04-16"},
 {"t": "CS51", "emp": "Cresud", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 5.75, "frec": "Semestral", "venc": "2027-01-19"},
 {"t": "DEC2", "emp": "Edesa", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 8.5, "frec": "Semestral", "venc": "2027-02-23"},
 {"t": "SIC1", "emp": "Sidersa", "ley": "ARG", "mon": "MEP", "calif": "A+(arg) (FIX)", "lam": "100", "cup": 6.5, "frec": "Semestral", "venc": "2026-12-08"},
 {"t": "GYC5", "emp": "360 Energy", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "50", "cup": 8.75, "frec": "Trimestral", "venc": "2027-09-04"},
 {"t": "YFCO", "emp": "Ypf Electrica", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "100", "cup": 6.75, "frec": "Trimestral", "venc": "2028-12-14"},
 {"t": "YMCZ", "emp": "YPF", "ley": "ARG", "mon": "CABLE", "calif": "AAA(arg) (FIX)", "lam": "1", "cup": 7.0, "frec": "Semestral", "venc": "2028-10-09"},
 {"t": "ZPC3", "emp": "Plaza Logistica", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1", "cup": 8.5, "frec": "Trimestral", "venc": "2027-09-02"},
 {"t": "CWC6", "emp": "Crown Point", "ley": "ARG", "mon": "MEP", "calif": "A+ (FIX)", "lam": "1", "cup": 9.5, "frec": "Semestral", "venc": "2027-10-29"},
 {"t": "MSSF", "emp": "MSU ENERGY", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 7.5, "frec": "Semestral", "venc": "2027-07-22"},
 {"t": "CLI1", "emp": "Clisa", "ley": "NY", "mon": "CABLE", "calif": "—", "lam": "1", "cup": 7.0, "frec": "Semestral", "venc": "2034-12-09"},
 {"t": "PUC2", "emp": "Petroleos Sudamericanos", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 8.75, "frec": "Semestral", "venc": "2027-08-27"},
 {"t": "CLSI", "emp": "Clisa", "ley": "NY", "mon": "CABLE", "calif": "BBB (arg)", "lam": "100", "cup": 3.5, "frec": "Semestral", "venc": "2031-12-09"},
 {"t": "FYC1", "emp": "Farmacity", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 7.5, "frec": "Semestral", "venc": "2029-05-10"},
 {"t": "AFCJ", "emp": "Banco Comafi", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "1.100", "cup": 4.75, "frec": "Semestral", "venc": "2027-02-05"},
 {"t": "AFCK", "emp": "Banco Comafi", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "1.100", "cup": 7.0, "frec": "Semestral", "venc": "2029-02-05"},
 {"t": "BF39", "emp": "Banco Bbva", "ley": "ARG", "mon": "MEP", "calif": "A1+(arg) (FIX)", "lam": "1", "cup": 5.75, "frec": "Semestral", "venc": "2026-12-04"},
 {"t": "BPCT", "emp": "Banco Supervielle", "ley": "ARG", "mon": "MEP", "calif": "AA+ (FIX)", "lam": "1", "cup": 8.0, "frec": "Semestral", "venc": "2027-08-25"},
 {"t": "BPCU", "emp": "Banco Supervielle", "ley": "ARG", "mon": "MEP", "calif": "ML A-1.ar (Moodys)", "lam": "1", "cup": 6.25, "frec": "Semestral", "venc": "2026-12-03"},
 {"t": "BPCV", "emp": "Banco Supervielle", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "1.100", "cup": 3.25, "frec": "Semestral", "venc": "2027-05-04"},
 {"t": "BVCR", "emp": "Bst", "ley": "ARG", "mon": "MEP", "calif": "ML A-1.ar (FIX)", "lam": "1", "cup": 7.0, "frec": "Trimestral", "venc": "2027-01-14"},
 {"t": "BYCX", "emp": "Banco Galicia", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "1.000", "cup": 5.5, "frec": "Semestral", "venc": "2026-12-29"},
 {"t": "CIC9", "emp": "Cnh", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 8.25, "frec": "Semestral", "venc": "2027-05-20"},
 {"t": "GN43", "emp": "Genneia", "ley": "ARG", "mon": "MEP", "calif": "AA (FIX)", "lam": "50", "cup": 6.25, "frec": "Trimestral", "venc": "2027-03-07"},
 {"t": "GOC4", "emp": "Generacion Litoral", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "1", "cup": 4.0, "frec": "Mensual", "venc": "2030-10-27"},
 {"t": "HBCD", "emp": "Banco Hipotecario", "ley": "ARG", "mon": "MEP", "calif": "A1+(arg) (FIX)", "lam": "1.000", "cup": 6.0, "frec": "Semestral", "venc": "2026-11-19"},
 {"t": "IRCQ", "emp": "IRSA", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 3.75, "frec": "Semestral", "venc": "2027-06-07"},
 {"t": "PN37", "emp": "PAE", "ley": "ARG", "mon": "MEP", "calif": "-", "lam": "50", "cup": 6.25, "frec": "Semestral", "venc": "2028-11-12"},
 {"t": "PQCT", "emp": "Petroquimica Comodoro Rivadavia", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "50", "cup": 8.5, "frec": "Semestral", "venc": "2028-07-20"},
 {"t": "PZCG", "emp": "Plaza Logistica", "ley": "ARG", "mon": "MEP", "calif": "AA (FIX)", "lam": "100", "cup": 7.0, "frec": "Trimestral", "venc": "2028-06-03"},
 {"t": "RZ9B", "emp": "Rizobacter", "ley": "ARG", "mon": "MEP", "calif": "A+ (FIX)", "lam": "100", "cup": 7.5, "frec": "Trimestral", "venc": "2026-06-27"},
 {"t": "RZBB", "emp": "Rizobacter", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 9.0, "frec": "Semestral", "venc": "2029-09-02"},
 {"t": "RZBC", "emp": "Rizobacter", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 9.0, "frec": "Semestral", "venc": "2029-09-02"},
 {"t": "T672", "emp": "Tarjeta Naranja", "ley": "ARG", "mon": "MEP", "calif": "—", "lam": "100", "cup": 5.0, "frec": "Trimestral", "venc": "2027-02-21"},
 {"t": "VBC1", "emp": "Banco De Valores", "ley": "ARG", "mon": "MEP", "calif": "AA+ (FIX)", "lam": "1.000", "cup": 7.5, "frec": "Semestral", "venc": "2027-03-10"},
 {"t": "ZPC2", "emp": "Plaza Logistica", "ley": "ARG", "mon": "MEP", "calif": "AA(arg) (FIX)", "lam": "1", "cup": 7.5, "frec": "Trimestral", "venc": "2027-06-01"}]
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


def completar(on):
    """Deja cada ON con los mismos campos: nombre limpio, empresa, cupón y frecuencia (para las que no vienen en META)."""
    nom = on.get("nombre") or ""
    nom = re.sub(r"^\S+\s+", "", nom)               # saca el ticker
    nom = re.sub(r"\s*\|.*$", "", nom)                 # saca "| Cotizaciones | Rava Bursátil"
    nom = re.sub(r"\s+\$\s?[\d.,]+.*$", "", nom).strip()  # saca el precio
    on["nombre"] = nom
    fl = on["flows"]
    if len(fl) >= 2 and not on.get("frec"):
        d = (fecha(fl[1][0]) - fecha(fl[0][0])).days
        on["frec"] = "Mensual" if d < 45 else "Trimestral" if d < 135 else "Semestral" if d < 270 else "Anual"
    on.setdefault("frec", "Semestral")
    if not on.get("cup") and fl:
        per = {"Mensual": 12, "Trimestral": 4, "Semestral": 2, "Anual": 1}.get(on.get("frec"), 2)
        regs = sorted(f[1] / f[3] for f in fl[1:] if f[3] > 0) or [fl[0][1] / max(fl[0][3], 1e-9)]
        on["cup"] = round(regs[len(regs) // 2] * per * 100, 2)
    if not on.get("emp"):
        on["emp"] = nom
    if not on.get("venc") and fl:
        on["venc"] = fl[-1][0]
    on.pop("texto_ficha", None)
    return on


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
            ons.append(completar(on))
        print(t, info.get("http"), info.get("fuente_flujo"), len(on["flows"]) if on else 0)
        time.sleep(0.8)
    with open("ons.json", "w", encoding="utf-8") as f:
        json.dump({"updated": HOY.isoformat(), "ons": ons}, f, ensure_ascii=False, separators=(",", ":"))
    with open("on_debug.json", "w", encoding="utf-8") as f:
        json.dump(debug, f, ensure_ascii=False, indent=1)
    print("Guardadas", len(ons), "ONs con flujo")


if __name__ == "__main__":
    main()
