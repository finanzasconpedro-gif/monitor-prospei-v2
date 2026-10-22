// Precios en vivo de los ETFs sectoriales y del S&P 500 (SPY), para "Rendimiento por sector" del monitor.
// Corre en Vercel (función del servidor): Yahoo no deja que el navegador le pida datos directo, pero sí el servidor.
// La respuesta queda en caché 55 segundos, así todos los que miran la página comparten la misma consulta.
const SYMS = ["SPY", "XLK", "XLV", "XLF", "XLE", "XLY", "XLP", "XLI", "XLB", "XLU", "XLC", "XLRE"];
const HOSTS = ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"];

async function quote(sym) {
  for (const h of HOSTS) {
    try {
      const r = await fetch(`${h}/v8/finance/chart/${sym}?range=1d&interval=5m`, {
        headers: { "User-Agent": "Mozilla/5.0 (PROSPEI monitor)" },
      });
      if (!r.ok) continue;
      const j = await r.json();
      const m = j && j.chart && j.chart.result && j.chart.result[0] && j.chart.result[0].meta;
      if (!m || !(m.regularMarketPrice > 0)) continue;
      const prev = m.chartPreviousClose || m.previousClose;
      if (!(prev > 0)) continue;
      // fecha de la rueda en Nueva York (para que la página no use la variación de una rueda vieja)
      const day = m.regularMarketTime
        ? new Date(m.regularMarketTime * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" })
        : null;
      return { symbol: sym, c: m.regularMarketPrice, prev, pct_change: (m.regularMarketPrice / prev - 1) * 100, day };
    } catch (e) {
      // se prueba con el otro servidor de Yahoo
    }
  }
  return null;
}

module.exports = async (req, res) => {
  const out = (await Promise.all(SYMS.map(quote))).filter(Boolean);
  res.setHeader("Cache-Control", "s-maxage=55, stale-while-revalidate=60");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.status(out.length ? 200 : 502).json(out);
};
