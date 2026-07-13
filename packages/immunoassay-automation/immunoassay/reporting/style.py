"""
reporting/style.py - the house style for the QC dossier, as one CSS string.

Matches the matcha-on-white look of the repo's other operator pages (the ODTC QC
report, the Tecan bench app): letterspaced uppercase eyebrows, a matcha accent, pill
chips, and a monospace block for anything machine-shaped. Kept as a single self-
contained string so a dossier is one HTML file an operator can mail to a partner site
with nothing else attached. Font is a system stack led by Manrope; if Manrope is
installed it is used, otherwise the page falls back cleanly.
"""

CSS = """
:root{
  --paper:#ffffff; --wash:#f4f8f4; --line:#e6ede7; --line2:#d7e3d9;
  --matcha:#5cae5a; --matcha-deep:#3c8446; --ink:#28372a; --muted:#5f7561;
  --amber:#b5811f; --amber-wash:#fbf3df; --red:#b03a34; --red-wash:#fbecea;
  --sans:"Manrope",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme: dark){
  :root{
    --paper:#0f1511; --wash:#151d17; --line:#233026; --line2:#2c3b2f;
    --matcha:#6fc06d; --matcha-deep:#8bd189; --ink:#e7f0e8; --muted:#9db3a1;
    --amber:#e0ad55; --amber-wash:#2a2113; --red:#e08079; --red-wash:#2a1614;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.6}
.wrap{max-width:960px;margin:0 auto;padding:48px clamp(18px,5vw,44px) 72px}
.eyebrow{text-transform:uppercase;font-weight:600;font-size:11px;letter-spacing:.34em;color:var(--matcha)}
h1{font-size:clamp(24px,4.5vw,34px);letter-spacing:.02em;margin:10px 0 6px;color:var(--ink)}
h2{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.16em;color:var(--matcha-deep);margin:0 0 14px}
.sub{color:var(--muted);font-size:14px;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:10px 22px;margin:18px 0 4px;font-size:13px;color:var(--muted)}
.meta b{color:var(--ink);font-weight:600}
.badge{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:700;letter-spacing:.04em;
  padding:7px 15px;border-radius:999px;text-transform:uppercase}
.badge.ok{color:#fff;background:var(--matcha-deep)}
.badge.stop{color:#fff;background:var(--red)}
.badge.wait{color:#fff;background:var(--amber)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
.chip{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:600;
  padding:6px 13px;border-radius:999px;border:1px solid var(--line2);color:var(--matcha-deep);background:var(--wash)}
.chip.amber{color:var(--amber);border-color:var(--amber);background:var(--amber-wash)}
.chip.red{color:var(--red);border-color:var(--red);background:var(--red-wash)}
.card{border:1px solid var(--line);border-radius:16px;padding:22px 22px 8px;margin:16px 0;background:var(--paper)}
.card.gate{border-left:4px solid var(--matcha)}
.card.gate.stop{border-left-color:var(--red)}
.card.gate.subset{border-left-color:var(--amber)}
.card .hd{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
.card .msg{color:var(--muted);font-size:14px;margin:2px 0 14px}
.flow{display:flex;flex-direction:column;gap:0}
.arrow{color:var(--matcha);text-align:center;font-size:15px;letter-spacing:.3em;margin:2px 0}
table{width:100%;border-collapse:collapse;font-size:13px;margin:4px 0 16px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--matcha);font-weight:700}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
tr.drop td{color:var(--muted);opacity:.75}
.pass{color:var(--matcha-deep);font-weight:700}
.fail{color:var(--red);font-weight:700}
.tablewrap{overflow-x:auto}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;font-size:13px;margin:0 0 14px}
.kv .k{color:var(--muted)}
.kv .v{color:var(--ink)}
.mono{font-family:var(--mono);font-size:12px}
pre{background:var(--wash);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto;
  font-family:var(--mono);font-size:12px;line-height:1.7;color:var(--ink)}
.note{border:1px solid var(--line2);background:var(--wash);border-radius:10px;padding:12px 15px;font-size:13px;color:var(--muted);margin:12px 0}
.note b{color:var(--ink)}
.foot{margin-top:36px;text-align:center;text-transform:uppercase;font-size:10px;font-weight:500;letter-spacing:.28em;color:var(--matcha);opacity:.7}
"""
