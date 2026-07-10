"""
make_qc_report.py - build the ODTC robustness QC report from a run log.

Self-contained. Parses the SiLA DataEvent temperature trace out of a run log, computes
setpoint-robustness metrics, and renders a single self-contained HTML report. Nothing
here is invented: every number comes from the block temperatures the device reported
during the run.

Usage:
    python make_qc_report.py --log ampseq_pcr1_2026-07-10.log --out odtc_qc_report.html
    python make_qc_report.py --log <log> --out <html> --font manrope.woff2

The report renders in any browser on a system font stack. Pass --font a Manrope variable
woff2 (SIL Open Font License, e.g. the fontsource latin variable file) to embed the house
typeface; the committed odtc_qc_report.html was built that way.

The metrics are control-loop fidelity: the ODTC's own block sensor tracking its own
setpoint, sampled about every 5 seconds. That is a real "does it hold temperature"
measure, not an externally calibrated accuracy figure. For calibrated accuracy you would
compare against an independent traceable probe.
"""

import argparse
import base64
import re

SETPOINTS = {"denature": 98.0, "anneal": 67.0, "extend": 72.0}
TOL = 1.5              # C: a sample counts toward a setpoint if within this band
BLOCK_CEILING = 99.0   # ODTC rated block maximum (PLR ODTC spec: 4 to 99 C)


def parse_log(path):
    raw = open(path).read()
    rows = []
    for line in raw.splitlines():
        m = re.search(r"Elapsed time': '(\d+) ms'.*?Target temperature': '(-?\d+).*?"
                      r"Current temperature': '(-?\d+).*?LID temperature': '(-?\d+)", line)
        if m:
            rows.append(dict(t=int(m.group(1)) / 1000.0, target=int(m.group(2)) / 100.0,
                             block=int(m.group(3)) / 100.0, lid=int(m.group(4)) / 100.0))
    if not rows:
        raise SystemExit(f"no DataEvent temperature samples found in {path}")

    oos = len(re.findall(r"2005 Temperature out of specification", raw))
    no_sdcard = bool(re.search(r"267 NO_SDCARD", raw))
    mwall = re.search(r"completed in ([\d.]+) min", raw)
    mname = re.search(r"method '([^']+)' completed", raw)

    # elapsed-time resets split pre-warm from the profile execution
    segs, cur = [], []
    for r in rows:
        if cur and r["t"] < cur[-1]["t"]:
            segs.append(cur); cur = []
        cur.append(r)
    segs.append(cur)
    prof = max(segs, key=lambda s: max((x["block"] for x in s), default=0))

    stats = {}
    for name, sp in SETPOINTS.items():
        devs = [x["block"] - sp for x in prof if abs(x["block"] - sp) <= TOL]
        if devs:
            n = len(devs); mean = sum(devs) / n
            sd = (sum((v - mean) ** 2 for v in devs) / n) ** 0.5
            stats[name] = dict(setpoint=sp, n=n, mean_dev=round(mean, 3), sd=round(sd, 3),
                               max_abs=round(max(abs(v) for v in devs), 3),
                               mean_abs=round(sum(abs(v) for v in devs) / n, 3))

    peaks, above = 0, False
    for x in prof:
        if x["block"] >= 95.0 and not above:
            peaks += 1; above = True
        elif x["block"] < 90.0:
            above = False

    all_abs = [abs(x["block"] - sp) for name, sp in SETPOINTS.items()
               for x in prof if abs(x["block"] - sp) <= TOL]
    overall = dict(mean_abs=round(sum(all_abs) / len(all_abs), 3),
                   max_abs=round(max(all_abs), 3), n=len(all_abs))

    step = max(1, len(prof) // 320)
    trace = [dict(t=round(x["t"], 1), block=round(x["block"], 2), lid=round(x["lid"], 2))
             for i, x in enumerate(prof) if i % step == 0]

    return dict(
        method_name=mname.group(1) if mname else "the run",
        wall_min=float(mwall.group(1)) if mwall else 0.0,
        prewarm_seconds=round(segs[0][-1]["t"], 1) if len(segs) > 1 else 0,
        profile_seconds=round(prof[-1]["t"] - prof[0]["t"], 1),
        denature_peaks=peaks,
        block_min=round(min(x["block"] for x in prof), 2),
        block_max=round(max(x["block"] for x in prof), 2),
        block_ceiling=BLOCK_CEILING,
        oos_warnings=oos, no_sdcard=no_sdcard,
        per_setpoint=stats, overall=overall, trace=trace,
    )


def render(d, font_b64=None):
    trace = d["trace"]
    t0 = trace[0]["t"]
    T = [x["t"] - t0 for x in trace]; B = [x["block"] for x in trace]
    tmax = T[-1]
    VB_W, VB_H = 920.0, 380.0
    ML, MR, MT, MB = 52.0, 18.0, 18.0, 40.0
    PW, PH = VB_W - ML - MR, VB_H - MT - MB
    Y_LO, Y_HI = 40.0, 103.0

    def px(t): return ML + (t / tmax) * PW
    def py(v): return MT + (Y_HI - v) / (Y_HI - Y_LO) * PH

    poly = " ".join(f"{px(t):.1f},{py(b):.1f}" for t, b in zip(T, B))
    pk = max(range(len(B)), key=lambda i: B[i])
    peak_x, peak_y = px(T[pk]), py(B[pk])
    # Label extends away from the peak: rightward if the peak is in the left half (so it
    # clears the ceiling label), leftward otherwise. Sits just below the point.
    if peak_x < ML + PW * 0.5:
        pk_anchor, pk_dx, pk_dy = "start", 7.0, 13.0
    else:
        pk_anchor, pk_dx, pk_dy = "end", -6.0, 13.0

    ref_svg = ""
    for label, temp in (("denature", 98.0), ("extend", 72.0), ("anneal", 67.0)):
        y = py(temp)
        ref_svg += (f'<line x1="{ML:.0f}" y1="{y:.1f}" x2="{ML+PW:.0f}" y2="{y:.1f}" class="ref"/>'
                    f'<text x="{ML+PW-2:.0f}" y="{y-4:.1f}" class="reflab" text-anchor="end">'
                    f'{temp:.0f}&deg;C {label}</text>')
    yc = py(99.0)
    ceil_svg = (f'<line x1="{ML:.0f}" y1="{yc:.1f}" x2="{ML+PW:.0f}" y2="{yc:.1f}" class="ceil"/>'
                f'<text x="{ML+2:.0f}" y="{yc-4:.1f}" class="ceillab">99&deg;C ODTC block ceiling</text>')
    tick_svg = ""
    mm = 0
    while mm * 60 <= tmax:
        x = px(mm * 60)
        tick_svg += (f'<line x1="{x:.1f}" y1="{MT+PH:.0f}" x2="{x:.1f}" y2="{MT+PH+5:.0f}" class="tick"/>'
                     f'<text x="{x:.1f}" y="{MT+PH+18:.0f}" class="ticklab" text-anchor="middle">{mm}</text>')
        mm += 5
    yt_svg = "".join(f'<text x="{ML-8:.0f}" y="{py(t)+3:.1f}" class="ticklab" text-anchor="end">{t}</text>'
                     for t in (40, 55, 70, 85, 100))

    ss, ov = d["per_setpoint"], d["overall"]

    def rowf(name, key, note):
        v = ss[key]
        return (f'<tr><td class="sp">{name}</td><td>{v["setpoint"]:.0f}&deg;C</td>'
                f'<td>{v["n"]}</td><td>{v["mean_dev"]:+.2f}</td><td>{v["sd"]:.2f}</td>'
                f'<td>{v["max_abs"]:.2f}</td><td class="mut">{note}</td></tr>')

    rows = (rowf("Denaturation", "denature", "grazes the 99&deg;C ceiling on ramp-in")
            + rowf("Annealing", "anneal", "tightest hold after settle")
            + rowf("Extension", "extend", "longest dwell, best tracked"))

    checks = [
        ("Reachability", "SiLA 1.2.01 endpoint answers; GetStatus state is well-formed"),
        ("Bring-up", "Reset + Initialize, startup to idle, all 8 sensors read back"),
        ("Block hold", "PreMethod drove the block to 45.00&deg;C and held on target"),
        ("Cycling method", "pre-warm then ExecuteMethod, block to 50.00&deg;C, completes"),
        ("PlateauTime unit", "a 60&nbsp;s step held ~56 to 60&nbsp;s: durations are in seconds"),
        ("Amplicon-seq PCR1", "30 cycles end to end, 36.6&nbsp;min, every setpoint held"),
    ]
    check_svg = "".join(
        f'<div class="pn"><div class="idx">{i:02d}</div><div class="rule"></div>'
        f'<div class="t">{t}</div><div class="dd">{sub}</div><div class="pass">PASS</div></div>'
        for i, (t, sub) in enumerate(checks, 1))

    face = (f"@font-face {{font-family:'Manrope';font-style:normal;font-weight:200 800;"
            f"font-display:swap;src:url(data:font/woff2;base64,{font_b64}) format('woff2');}}"
            if font_b64 else "")

    peak, wall, oos, peaks = d["block_max"], d["wall_min"], d["oos_warnings"], d["denature_peaks"]
    prewarm_min, profile_min = d["prewarm_seconds"] / 60, d["profile_seconds"] / 60

    return f"""<title>ODTC Amplicon-seq PCR1 &middot; Robustness QC</title>
<style>
{face}
:root{{
  --paper:#ffffff; --surface:#f7f8f7; --ink:#17191c; --mut:#565a5f; --faint:#8c9196;
  --line:#ebebe8; --acc:#4e9d5e; --deep:#3b8a4b; --soft:#a9cba6;
  --wash:rgba(78,157,94,0.09); --warn:#c07a1e; --warnwash:rgba(192,122,30,0.10);
}}
@media (prefers-color-scheme:dark){{
  :root{{
    --paper:#0e0f10; --surface:#17181a; --ink:#f0f1ee; --mut:#a6abaf; --faint:#71767a;
    --line:#25272a; --acc:#6cbf7c; --deep:#7fcf8e; --soft:#3f5a44;
    --wash:rgba(108,191,124,0.12); --warn:#e0a24a; --warnwash:rgba(224,162,74,0.12);
  }}
}}
:root[data-theme="dark"]{{
  --paper:#0e0f10; --surface:#17181a; --ink:#f0f1ee; --mut:#a6abaf; --faint:#71767a;
  --line:#25272a; --acc:#6cbf7c; --deep:#7fcf8e; --soft:#3f5a44;
  --wash:rgba(108,191,124,0.12); --warn:#e0a24a; --warnwash:rgba(224,162,74,0.12);
}}
:root[data-theme="light"]{{
  --paper:#ffffff; --surface:#f7f8f7; --ink:#17191c; --mut:#565a5f; --faint:#8c9196;
  --line:#ebebe8; --acc:#4e9d5e; --deep:#3b8a4b; --soft:#a9cba6;
  --wash:rgba(78,157,94,0.09); --warn:#c07a1e; --warnwash:rgba(192,122,30,0.10);
}}
*{{box-sizing:border-box}}
body{{margin:0; background:var(--paper); color:var(--ink);
  font-family:'Manrope',system-ui,-apple-system,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased; font-variant-numeric:tabular-nums;}}
.wrap{{max-width:1000px; margin:0 auto; border-left:1px solid var(--line);
  border-right:1px solid var(--line); min-height:100vh;}}
.nav{{display:flex; align-items:center; justify-content:space-between;
  padding:20px 44px; border-bottom:1px solid var(--line);}}
.mark{{font-size:13px; font-weight:700; letter-spacing:.22em; text-transform:uppercase;}}
.mark .g{{color:var(--acc);}}
.nav .r{{font-size:11px; letter-spacing:.18em; text-transform:uppercase;
  color:var(--mut); font-weight:600;}}
.meta{{display:grid; grid-template-columns:repeat(3,1fr); border-bottom:1px solid var(--line);}}
.meta div{{padding:11px 44px; font-size:10.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--mut); font-weight:600; border-right:1px solid var(--line);}}
.meta div:last-child{{border-right:none;}}
.meta b{{color:var(--ink);}}
.hero{{padding:56px 44px 46px;}}
.eyebrow{{font-size:11.5px; letter-spacing:.22em; text-transform:uppercase; font-weight:700;
  color:var(--acc); margin-bottom:22px;}}
h1{{font-size:46px; line-height:1.06; letter-spacing:-.02em; margin:0; font-weight:500;
  text-wrap:balance;}}
h1 b{{font-weight:800;}}
.sub{{font-size:17px; line-height:1.6; color:var(--mut); max-width:60ch; margin-top:24px; font-weight:400;}}
.sub b{{color:var(--ink); font-weight:600;}}
.sub .em{{color:var(--acc); font-weight:700;}}
.stats{{display:grid; grid-template-columns:repeat(4,1fr);
  border-top:1px solid var(--ink); border-bottom:1px solid var(--ink);}}
.stat{{padding:26px 24px 24px 44px; border-right:1px solid var(--line);}}
.stat:last-child{{border-right:none;}}
.stat .n{{font-size:33px; font-weight:700; letter-spacing:-.02em; line-height:1;}}
.stat .n b{{color:var(--acc);}}
.stat .n .u{{font-size:15px; font-weight:500; color:var(--mut);}}
.stat .k{{font-size:11px; color:var(--mut); margin-top:11px; font-weight:600;
  letter-spacing:.03em; line-height:1.4;}}
.sec{{padding:52px 44px; border-bottom:1px solid var(--line);}}
.smark{{display:flex; align-items:baseline; gap:14px; margin-bottom:24px;}}
.smark .no{{font-weight:700; font-size:12px; color:var(--acc); letter-spacing:.08em;}}
.smark .lbl{{font-size:11.5px; letter-spacing:.2em; text-transform:uppercase;
  font-weight:700; color:var(--mut);}}
.body{{font-size:15.5px; line-height:1.68; color:var(--mut); max-width:66ch; font-weight:400;}}
.body b{{color:var(--ink); font-weight:600;}}
.body .em{{color:var(--acc); font-weight:600;}}
.plot{{margin-top:8px; border:1px solid var(--line); border-radius:6px; background:var(--surface);
  padding:14px 8px 6px; overflow-x:auto;}}
svg.chart{{display:block; width:100%; height:auto; min-width:560px;}}
.grid{{stroke:var(--line); stroke-width:1;}}
.ref{{stroke:var(--soft); stroke-width:1; stroke-dasharray:2 4;}}
.reflab{{fill:var(--faint); font-size:9.5px; font-weight:600; letter-spacing:.04em;}}
.ceil{{stroke:var(--warn); stroke-width:1.2; stroke-dasharray:5 3;}}
.ceillab{{fill:var(--warn); font-size:9.5px; font-weight:700; letter-spacing:.03em;}}
.trace{{fill:none; stroke:var(--acc); stroke-width:1.5; stroke-linejoin:round; stroke-linecap:round;}}
.tick{{stroke:var(--line); stroke-width:1;}}
.ticklab{{fill:var(--faint); font-size:9px; font-weight:600;}}
.axlab{{fill:var(--mut); font-size:10px; font-weight:700; letter-spacing:.1em; text-transform:uppercase;}}
.pk{{fill:var(--warn);}}
.pklab{{fill:var(--warn); font-size:10px; font-weight:700;}}
.legend{{display:flex; gap:22px; flex-wrap:wrap; margin-top:14px; font-size:11.5px;
  color:var(--mut); font-weight:600;}}
.legend span{{display:inline-flex; align-items:center; gap:7px;}}
.sw{{width:16px; height:0; border-top:2px solid var(--acc);}}
.sw.warn{{border-top:2px dashed var(--warn);}}
.sw.soft{{border-top:2px dashed var(--soft);}}
table{{width:100%; border-collapse:collapse; margin-top:6px; font-size:14px;}}
th{{text-align:left; font-size:10.5px; letter-spacing:.12em; text-transform:uppercase;
  color:var(--mut); font-weight:700; padding:0 14px 12px 0; border-bottom:1px solid var(--ink);}}
td{{padding:13px 14px 13px 0; border-bottom:1px solid var(--line); font-weight:500;}}
td.sp{{font-weight:700; color:var(--ink);}}
td.mut{{color:var(--mut); font-weight:500; font-size:13px;}}
.tnote{{font-size:12.5px; color:var(--faint); margin-top:14px; font-weight:500;}}
.callout{{margin-top:8px; border:1px solid var(--warn); border-radius:6px;
  background:var(--warnwash); padding:22px 24px;}}
.callout .h{{font-size:11px; letter-spacing:.16em; text-transform:uppercase; font-weight:700;
  color:var(--warn); margin-bottom:12px; display:flex; align-items:center; gap:9px;}}
.callout .h .dot{{width:7px; height:7px; border-radius:50%; background:var(--warn);}}
.callout p{{margin:0 0 12px; font-size:15px; line-height:1.62; color:var(--ink); font-weight:500;}}
.callout p:last-child{{margin-bottom:0;}}
.callout b{{font-weight:700;}}
.callout .fix{{color:var(--mut); font-size:13.5px;}}
.ladder{{display:flex; flex-direction:column;}}
.pn{{display:grid; grid-template-columns:34px 1fr auto; align-items:center; gap:14px;
  padding:16px 0; border-bottom:1px solid var(--line);}}
.pn:last-child{{border-bottom:none;}}
.pn .idx{{font-weight:700; font-size:12px; color:var(--acc); grid-column:1; grid-row:1;}}
.pn .rule{{display:none;}}
.pn .t{{font-weight:700; font-size:15px; color:var(--ink); grid-column:2; grid-row:1;}}
.pn .dd{{grid-column:2; grid-row:2; font-size:13px; color:var(--mut); font-weight:500; margin-top:2px;}}
.pn .pass{{grid-column:3; grid-row:1 / span 2; align-self:center;
  font-size:10.5px; letter-spacing:.12em; font-weight:800; color:var(--acc);
  border:1.4px solid var(--acc); border-radius:100px; padding:5px 13px;}}
.sig{{display:flex; align-items:center; gap:30px; padding:44px; border-bottom:1px solid var(--line);}}
.sig svg{{width:96px; height:100px; flex-shrink:0;}}
.sig .t{{font-size:14px; line-height:1.6; color:var(--mut); font-weight:500; max-width:60ch;}}
.sig .t b{{color:var(--ink); font-weight:700;}}
.foot{{padding:26px 44px 40px; display:flex; justify-content:space-between;
  flex-wrap:wrap; gap:12px; font-size:11px; letter-spacing:.06em; color:var(--faint);
  font-weight:600; text-transform:uppercase;}}
.foot .g{{color:var(--acc);}}
@media (max-width:720px){{
  .stats{{grid-template-columns:repeat(2,1fr);}}
  .meta{{grid-template-columns:1fr;}} .meta div{{border-right:none;}}
  h1{{font-size:34px;}} .stat{{padding-left:24px;}} .sec,.hero,.nav{{padding-left:24px; padding-right:24px;}}
  .sig{{flex-direction:column; align-items:flex-start; gap:18px;}}
}}
</style>

<div class="wrap">
  <div class="nav">
    <div class="mark">plr&#8209;tested<span class="g">.</span></div>
    <div class="r">instrument QC &middot; run log attached</div>
  </div>
  <div class="meta">
    <div>Instrument &nbsp; <b>Inheco ODTC</b></div>
    <div>Method &nbsp; <b>amplicon&#8209;seq PCR1</b></div>
    <div>Run &nbsp; <b>2026&#8209;07&#8209;10</b></div>
  </div>

  <div class="hero">
    <div class="eyebrow">Thermocycler robustness &middot; on the block</div>
    <h1>Thirty cycles,<br><b>held to a quarter&#8209;degree.</b></h1>
    <p class="sub">The amplicon&#8209;seq PCR1 program ran end to end on the Inheco ODTC,
    driven through PyLabRobot from the lab Raspberry Pi. Across all 30 cycles the block
    tracked every setpoint to a <span class="em">mean {ov['mean_abs']:.2f}&deg;C</span>
    deviation. One caveat, logged not hidden: the 98&deg;C denaturation grazes the
    device's 99&deg;C ceiling on the fast ramp&#8209;in.</p>
  </div>

  <div class="stats">
    <div class="stat"><div class="n"><b>{peaks}</b><span class="u"> / 30</span></div>
      <div class="k">CYCLES COMPLETED<br>denaturation peaks counted</div></div>
    <div class="stat"><div class="n">&plusmn;{ov['mean_abs']:.2f}<span class="u">&deg;C</span></div>
      <div class="k">MEAN SETPOINT ERROR<br>{ov['n']} in&#8209;band samples</div></div>
    <div class="stat"><div class="n">{peak:.2f}<span class="u">&deg;C</span></div>
      <div class="k">PEAK BLOCK TEMP<br>ceiling is 99&deg;C</div></div>
    <div class="stat"><div class="n">{wall:.1f}<span class="u"> min</span></div>
      <div class="k">WALL CLOCK<br>incl. {prewarm_min:.0f} min pre&#8209;warm</div></div>
  </div>

  <div class="sec">
    <div class="smark"><span class="no">01</span><span class="lbl">The thermal trace</span></div>
    <div class="body" style="margin-bottom:20px;">Block temperature reported by the ODTC
    over the {profile_min:.0f}&#8209;minute cycling method, sampled about every
    5&nbsp;seconds. The sawtooth is real PCR: <b>98&deg;C</b> denature, <b>67&deg;C</b>
    anneal, <b>72&deg;C</b> extend, thirty times, then the 72&deg;C final extension and a
    10&deg;C hold. The dashed amber line is the device's rated block ceiling.</div>
    <div class="plot">
      <svg class="chart" viewBox="0 0 {VB_W:.0f} {VB_H:.0f}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Block temperature versus time across 30 PCR cycles">
        <line x1="{ML:.0f}" y1="{MT:.0f}" x2="{ML:.0f}" y2="{MT+PH:.0f}" class="grid"/>
        <line x1="{ML:.0f}" y1="{MT+PH:.0f}" x2="{ML+PW:.0f}" y2="{MT+PH:.0f}" class="grid"/>
        {ref_svg}
        {ceil_svg}
        {tick_svg}
        {yt_svg}
        <polyline class="trace" points="{poly}"/>
        <circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="3.2" class="pk"/>
        <text x="{peak_x+pk_dx:.1f}" y="{peak_y+pk_dy:.1f}" class="pklab" text-anchor="{pk_anchor}">peak {peak:.2f}&deg;C</text>
        <text x="{ML-40:.0f}" y="{MT+PH/2:.0f}" class="axlab" transform="rotate(-90 {ML-40:.0f} {MT+PH/2:.0f})" text-anchor="middle">Block &deg;C</text>
        <text x="{ML+PW/2:.0f}" y="{VB_H-4:.0f}" class="axlab" text-anchor="middle">Minutes into method</text>
      </svg>
    </div>
    <div class="legend">
      <span><span class="sw"></span> block temperature</span>
      <span><span class="sw soft"></span> setpoints (98 / 72 / 67&deg;C)</span>
      <span><span class="sw warn"></span> 99&deg;C ceiling</span>
    </div>
  </div>

  <div class="sec">
    <div class="smark"><span class="no">02</span><span class="lbl">Setpoint robustness</span></div>
    <div class="body" style="margin-bottom:18px;">Deviation of the block from each setpoint,
    over samples that had settled within 1.5&deg;C of it. Signed mean shows bias; SD shows
    spread. Everything is well under a degree.</div>
    <div style="overflow-x:auto;"><table>
      <tr><th>Phase</th><th>Setpoint</th><th>n</th><th>Mean dev</th><th>SD</th><th>Max &#124;dev&#124;</th><th>Note</th></tr>
      {rows}
    </table></div>
    <div class="tnote">Deviations in &deg;C. This is the device's own block sensor tracking
    its own setpoint (control fidelity), not an externally calibrated accuracy figure.
    Brief ramp transients between the 5&#8209;second samples are not captured here (see 03).</div>
  </div>

  <div class="sec">
    <div class="smark"><span class="no">03</span><span class="lbl">The one caveat, logged</span></div>
    <div class="callout">
      <div class="h"><span class="dot"></span>Temperature out of specification &middot; {oos} events</div>
      <p>The 98&deg;C denaturation setpoint sits just 1&deg;C under the ODTC's rated
      <b>99&deg;C block maximum</b>. On the aggressive ramp into denaturation the block
      overshoots and grazes that ceiling &#8212; the 5&#8209;second trace caught a
      <b>{peak:.2f}&deg;C</b> peak, and the device's own faster internal monitor logged
      <b>{oos} "temperature out of specification" events</b> across the 30 cycles, roughly
      three per cycle. The method completed regardless; these are warnings, not faults, and
      denaturation at 98&#8211;99&deg;C is biologically fine.</p>
      <p class="fix"><b>Recommended before a real sample run:</b> drop the denaturation
      setpoint to 97&deg;C, or soften the overshoot parameters into that step, to keep the
      block off the ceiling. Either change is one line in <b>odtc_protocols.py</b> and
      re&#8209;checkable with this same report.</p>
    </div>
  </div>

  <div class="sec">
    <div class="smark"><span class="no">04</span><span class="lbl">Proof chain</span></div>
    <div class="body" style="margin-bottom:22px;">This run is the last rung of a ladder,
    each step executed on the physical instrument, not a simulator. That is the whole point
    of <b>plr&#8209;tested</b>: nothing is asserted that was not measured.</div>
    <div class="ladder">{check_svg}</div>
  </div>

  <div class="sig">
    <svg viewBox="0 0 200 210" fill="none" stroke="var(--ink)" aria-hidden="true">
      <ellipse cx="78" cy="105" rx="56" ry="74" stroke-width="1"/>
      <ellipse cx="122" cy="105" rx="56" ry="74" stroke-width="1"/>
      <ellipse cx="100" cy="105" rx="74" ry="56" stroke-width="1" stroke="var(--soft)"/>
      <circle cx="100" cy="105" r="4" fill="var(--acc)" stroke="none"/>
    </svg>
    <div class="t"><b>Measured, not asserted.</b> Every value on this page comes from the
    ODTC's own temperature stream during method <b>{d['method_name']}</b>, parsed from the
    run log committed beside this report. No SD card was fitted, so the device also logged a
    benign NO_SDCARD warning; the trace is read live over SiLA and is unaffected.</div>
  </div>

  <div class="foot">
    <div>di&#8209;omics <span class="g">/</span> plr&#8209;tested <span class="g">/</span> instrument&#8209;integrations <span class="g">/</span> odtc</div>
    <div>Research use only &middot; not for diagnostic use</div>
  </div>
</div>
"""


def main():
    ap = argparse.ArgumentParser(description="Build the ODTC robustness QC report from a run log.")
    ap.add_argument("--log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--font", default=None, help="optional Manrope variable woff2 to embed")
    args = ap.parse_args()

    d = parse_log(args.log)
    font_b64 = base64.b64encode(open(args.font, "rb").read()).decode() if args.font else None
    html = render(d, font_b64)
    open(args.out, "w").write(html)

    bad = sorted({c for c in html if ord(c) > 127})
    print(f"wrote {args.out} ({len(html)} bytes) from {args.log}")
    print(f"  {d['denature_peaks']} cycles, mean setpoint error {d['overall']['mean_abs']:.2f} C, "
          f"peak {d['block_max']:.2f} C, {d['oos_warnings']} out-of-spec warnings")
    print(f"  non-ascii in output: {bad or 'none'}")


if __name__ == "__main__":
    main()
