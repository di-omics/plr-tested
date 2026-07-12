"""
reporting/report.py - the run dossier.

One self-contained HTML file per run: the header (who, what, mode, verdict), the provenance
summary, then the stage-by-stage flow with each gate's decision and the data it decided from,
ending in the response calls and the next-run recommendations. This is the audit artifact -
the thing a partner site, an auditor, or a future self reads to see not just that the run
passed, but exactly which antigen cleared which cutoff against which background, and where
every value came from.

It renders from the RunOutcome object directly. Nothing here recomputes a result; it only
presents what the orchestrator already decided.
"""

from __future__ import annotations

import html

from ..gates import Decision
from ..orchestrator import RunOutcome, RunStatus
from ..stages.base import StageStatus
from .style import CSS


def _esc(x) -> str:
    return html.escape(str(x))


def _status_badge(status: RunStatus) -> str:
    cls = {"completed": "ok", "stopped": "stop", "awaiting_data": "wait"}[status.value]
    label = {"completed": "Completed", "stopped": "Stopped",
             "awaiting_data": "Awaiting data"}[status.value]
    return f'<span class="badge {cls}">{label}</span>'


def _pf(passed: bool) -> str:
    return '<span class="pass">PASS</span>' if passed else '<span class="fail">FAIL</span>'


def _gate_run_table(gate) -> str:
    if not gate or not gate.run_outcomes:
        return ""
    rows = []
    for o in gate.run_outcomes:
        rows.append(
            f"<tr><td>{_esc(o.criterion.label)}</td>"
            f"<td class='num'>{_esc(o.criterion.bound_label())}</td>"
            f"<td class='num'>{_esc(round(o.measured, 4))}</td>"
            f"<td>{_pf(o.passed)}</td></tr>"
        )
    return (
        "<div class='tablewrap'><table><tr><th>Run-level criterion</th><th>Requirement</th>"
        "<th>Measured</th><th></th></tr>" + "".join(rows) + "</table></div>"
    )


def _readiness_body(data: dict) -> str:
    rows = []
    for v in data.get("volumes", []):
        rows.append(
            f"<tr><td class='num'>{_esc(v['volume_ul'])}</td><td class='num'>{_esc(v['n'])}</td>"
            f"<td class='num'>{_esc(v['cv_percent'])}</td>"
            f"<td class='num'>{_esc(v['cutoff_percent'])}</td><td>{_pf(v['passed'])}</td></tr>"
        )
    table = (
        "<div class='tablewrap'><table><tr><th>Volume (uL)</th><th>n</th><th>CV %</th>"
        "<th>Cutoff %</th><th></th></tr>" + "".join(rows) + "</table></div>"
    )
    note = (
        f"<div class='note'><b>Method.</b> {_esc(data.get('method',''))}. "
        f"Linearity R-squared {_esc(data.get('linearity_r2'))}; "
        f"aspiration residual {_esc(data.get('residual_mean_ul'))} uL mean / "
        f"{_esc(data.get('residual_max_ul'))} uL max (cutoff {_esc(data.get('residual_cutoff_ul'))} uL). "
        f"Membrane clearance: {_esc(data.get('membrane_clearance'))}.</div>"
    )
    return table + note


def _plate_prep_body(data: dict) -> str:
    return (
        "<div class='kv'>"
        f"<div class='k'>Cytokine</div><div class='v'>{_esc(data.get('cytokine'))}</div>"
        f"<div class='k'>Pre-wet</div><div class='v'>{_esc(data.get('prewet_ethanol_percent'))}% ethanol, "
        f"{_esc(data.get('prewet_volume_ul'))} uL/well, CV {_esc(data.get('prewet_cv_percent'))}% "
        f"(cutoff {_esc(data.get('prewet_cutoff_percent'))}%)</div>"
        f"<div class='k'>Coat</div><div class='v'>{_esc(data.get('coat'))}</div>"
        f"<div class='k'>Block</div><div class='v'>{_esc(data.get('block'))}</div>"
        f"<div class='k'>Dispense</div><div class='v mono'>{_esc(data.get('dispense_mode'))}</div>"
        "</div>"
    )


def _stimulation_body(data: dict) -> str:
    layout_rows = []
    for w in data.get("layout", []):
        layout_rows.append(
            f"<tr><td>{_esc(w['well'])}</td><td>{_esc(w['role'])}</td>"
            f"<td>{_esc(w['antigen'])}</td><td class='num'>{_esc(w['cells'])}</td></tr>"
        )
    table = (
        "<div class='tablewrap'><table><tr><th>Well</th><th>Role</th><th>Antigen</th>"
        "<th>Cells</th></tr>" + "".join(layout_rows) + "</table></div>"
    )
    note = (
        f"<div class='note'><b>Incubation.</b> {_esc(data.get('incubation'))}. "
        f"{_esc(data.get('do_not_disturb',''))}.</div>"
    )
    return table + note


def _develop_body(data: dict) -> str:
    steps = " &#8594; ".join(_esc(s) for s in data.get("steps", []))
    return (
        f"<div class='note'><b>Chain.</b> {steps}.</div>"
        "<div class='kv'>"
        f"<div class='k'>Wash</div><div class='v'>{_esc(data.get('wash_cycles'))} cycles x "
        f"{_esc(data.get('wash_volume_ul'))} uL, aspiration height "
        f"{_esc(data.get('aspiration_height_mm'))} mm</div>"
        f"<div class='k'>Development endpoint</div><div class='v mono'>{_esc(data.get('development_endpoint'))} "
        f"[{_esc(data.get('development_endpoint_origin'))}]</div>"
        f"<div class='k'>Stop / dry</div><div class='v'>{_esc(data.get('stop_and_dry'))}</div>"
        "</div>"
    )


def _response_chip(r: dict) -> str:
    if r.get("saturated"):
        return "<span class='chip amber'>TNTC</span>"
    if r.get("positive"):
        return "<span class='chip'>positive</span>"
    return "<span class='chip'>negative</span>"


def _response_table(responses: list) -> str:
    rows = []
    for r in responses:
        cls = "" if r.get("replicate_cv_ok", True) else "drop"
        cv = r.get("replicate_cv_percent")
        cv_txt = "n/a" if cv is None else f"{cv}%"
        rows.append(
            f"<tr class='{cls}'><td>{_esc(r['antigen'])}</td>"
            f"<td class='num'>{_esc(r['test_mean_sfu'])}</td>"
            f"<td class='num'>{_esc(r['background_mean_sfu'])}</td>"
            f"<td class='num'>{_esc(r['net_sfu'])}</td>"
            f"<td class='num'>{_esc(r['stimulation_index'])}</td>"
            f"<td class='num'>{_esc(r['net_per_million'])}</td>"
            f"<td class='num'>{_esc(cv_txt)}</td>"
            f"<td>{_response_chip(r)}</td></tr>"
        )
    return (
        "<div class='tablewrap'><table><tr><th>Antigen</th><th>Mean SFU</th><th>Bkg SFU</th>"
        "<th>Net SFU</th><th>SI</th><th>Net/1e6</th><th>Rep CV</th><th>Call</th></tr>"
        + "".join(rows) + "</table></div>"
    )


def _readout_body(data: dict) -> str:
    validity = (
        f"<div class='note'><b>Plate validity.</b> Positive control "
        f"{_esc(data.get('pos_ctrl_mean_sfu'))} SFU (floor {_esc(data.get('pos_ctrl_floor_sfu'))}); "
        f"background {_esc(data.get('background_mean_sfu'))} SFU "
        f"(ceiling {_esc(data.get('background_ceiling_sfu'))}); "
        f"saturation ceiling {_esc(data.get('saturation_sfu'))} SFU.</div>"
    )
    return validity + _response_table(data.get("responses", []))


def _handoff_body(data: dict) -> str:
    table = _response_table(data.get("responses", []))
    rec_items = "".join(
        f"<tr><td>{_esc(r['trigger'])}</td><td>{_esc(r['action'])}</td></tr>"
        for r in data.get("recommendations", [])
    )
    recs = (
        "<h2 style='margin-top:8px'>Next-run recommendations</h2>"
        "<div class='tablewrap'><table><tr><th>Trigger</th><th>Action</th></tr>"
        + rec_items + "</table></div>"
    )
    dropped = data.get("dropped_antigens", [])
    drop_note = (f"<div class='note'><b>Dropped (untrustworthy):</b> {_esc(', '.join(dropped))}.</div>"
                 if dropped else "")
    csv = data.get("results_csv", "")
    sheet = f"<h2 style='margin-top:8px'>Results CSV</h2><pre>{_esc(csv)}</pre>" if csv else ""
    return table + drop_note + recs + sheet


_BODY = {
    "readiness": _readiness_body,
    "plate_prep": _plate_prep_body,
    "stimulation": _stimulation_body,
    "develop": _develop_body,
    "readout": _readout_body,
    "handoff": _handoff_body,
}


def _stage_card(stage) -> str:
    gate = stage.gate
    gate_cls = ""
    if gate:
        if gate.decision is Decision.STOP:
            gate_cls = "gate stop"
        elif gate.decision is Decision.PROCEED_SUBSET:
            gate_cls = "gate subset"
        else:
            gate_cls = "gate"
    status_chip = {
        StageStatus.COMPLETED: "<span class='chip'>completed</span>",
        StageStatus.STOPPED: "<span class='chip red'>stopped</span>",
        StageStatus.AWAITING_DATA: "<span class='chip amber'>awaiting data</span>",
    }[stage.status]

    body = ""
    if stage.name in _BODY and stage.data:
        body += _BODY[stage.name](stage.data)
    body += _gate_run_table(gate)

    if gate and gate.dropped_sample_ids():
        dropped = ", ".join(gate.dropped_sample_ids())
        body += f"<div class='note'><b>Wells dropped here:</b> {_esc(dropped)} (did not meet the gate).</div>"

    if stage.status is StageStatus.AWAITING_DATA:
        body += f"<pre>{_esc(stage.message)}</pre>"

    return (
        f"<div class='card {gate_cls}'>"
        f"<div class='hd'><div><h2 style='margin-bottom:4px'>{_esc(stage.title)}</h2>"
        f"<div class='msg'>{_esc(stage.message)}</div></div>{status_chip}</div>"
        f"{body}</div>"
    )


def render_dossier(outcome: RunOutcome) -> str:
    cfg = outcome.config
    g = outcome.guard_summary
    guard_chips = "".join(
        f"<span class='chip{' amber' if k == 'calibrate' else ' red' if k == 'todo' else ''}'>"
        f"{_esc(v)} {_esc(k)}</span>"
        for k, v in g.items() if v
    )
    blocking = ""
    if outcome.guard_blocking:
        items = "".join(f"<li class='mono'>{_esc(b)}</li>" for b in outcome.guard_blocking)
        blocking = (f"<div class='note'><b>Blocking a hardware run</b> until resolved:"
                    f"<ul>{items}</ul></div>")

    flow = []
    for i, stage in enumerate(outcome.stages):
        if i > 0:
            flow.append("<div class='arrow'>&#9660;</div>")
        flow.append(_stage_card(stage))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ELISpot dossier - {_esc(cfg.run_id)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
  <div class="eyebrow">ELISpot automation package</div>
  <h1>{_esc(cfg.run_id)}</h1>
  <p class="sub">QC-gated {_esc(cfg.cytokine)} ELISpot on a washer + liquid handler + spot imager, driven from a Pi.</p>
  <div class="meta">
    <span>Operator <b>{_esc(cfg.operator)}</b></span>
    <span>Mode <b>{_esc(cfg.mode.value)}</b></span>
    <span>Site <b>{_esc(cfg.site.name)}</b></span>
    <span>Run at <b>{_esc(outcome.timestamp or 'n/a')}</b></span>
    <span>{_status_badge(outcome.status)}</span>
  </div>
  <p class="sub" style="margin-top:10px">{_esc(outcome.message)}.</p>
  <div class="chips">{guard_chips}</div>
  {blocking}
  <div class="flow">{''.join(flow)}</div>
  <div class="foot">di-omics &#183; plr-tested &#183; elispot</div>
</div></body></html>"""
