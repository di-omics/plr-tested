"""
reporting/report.py - the run dossier.

One self-contained HTML file per run: the header (who, what, mode, verdict), the
provenance summary, then the stage-by-stage flow with each gate's decision and the data
it decided from. This is the audit artifact - the thing a partner site, an auditor, or a
future self reads to see not just that the run passed, but exactly which wells passed
which gate against which cutoff, and where any value came from.

It renders from the RunOutcome object directly. Nothing here recomputes a result; it
only presents what the orchestrator already decided.
"""

from __future__ import annotations

import html
from typing import List

from ..gates import Decision
from ..orchestrator import RunOutcome, RunStatus
from ..stages.base import StageStatus
from .style import CSS


def _esc(x) -> str:
    return html.escape(str(x))


def _status_badge(status: RunStatus) -> str:
    cls = {"completed": "ok", "stopped": "stop", "awaiting_data": "wait"}[status.value]
    label = {"completed": "Completed", "stopped": "Stopped", "awaiting_data": "Awaiting data"}[status.value]
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


def _lh_qc_body(data: dict) -> str:
    rows = []
    for v in data.get("volumes", []):
        rows.append(
            f"<tr><td class='num'>{_esc(v['volume_ul'])}</td><td>{_esc(v['tip'])}</td>"
            f"<td class='num'>{_esc(v['n'])}</td><td class='num'>{_esc(v['cv_percent'])}</td>"
            f"<td class='num'>{_esc(v['cutoff_percent'])}</td><td>{_pf(v['passed'])}</td></tr>"
        )
    table = (
        "<div class='tablewrap'><table><tr><th>Volume (uL)</th><th>Tip</th><th>n</th>"
        "<th>CV %</th><th>Cutoff %</th><th></th></tr>" + "".join(rows) + "</table></div>"
    )
    note = (
        f"<div class='note'><b>Method.</b> {_esc(data.get('method',''))}. "
        f"Read ex {_esc(data.get('read_ex_nm'))} nm / em {_esc(data.get('read_em_nm'))} nm, "
        f"common read volume {_esc(data.get('common_read_volume_ul'))} uL. "
        f"Signal-vs-volume linearity R-squared {_esc(data.get('linearity_r2'))}.</div>"
    )
    return table + note


def _wgs_prep_body(data: dict) -> str:
    return (
        "<div class='kv'>"
        f"<div class='k'>Wells</div><div class='v mono'>{_esc(', '.join(data.get('wells', [])))}</div>"
        f"<div class='k'>WGS preparation program</div><div class='v'>{_esc(data.get('wgs_prep_program'))}</div>"
        f"<div class='k'>Source</div><div class='v'>{_esc(data.get('wgs_prep_source'))}</div>"
        f"<div class='k'>Lysis / reaction</div><div class='v mono'>{_esc(data.get('lysis_ul'))} uL / {_esc(data.get('reaction_ul'))} uL</div>"
        "</div>"
        f"<div class='note'>{_esc(data.get('wgs_prep_note',''))}</div>"
    )


def _fluorescent_dsdna_body(data: dict) -> str:
    rows = []
    for s in data.get("samples", []):
        cls = "" if s["passed"] else "drop"
        flag = "" if s.get("in_curve_range", True) else " *"
        rows.append(
            f"<tr class='{cls}'><td>{_esc(s['sample_id'])}</td><td>{_esc(s['well'])}</td>"
            f"<td>{_esc(s['sample_type'])}</td>"
            f"<td class='num'>{_esc(s['concentration_ng_per_ul'])}{flag}</td>"
            f"<td class='num'>{_esc(s['mass_ng'])}</td><td>{_pf(s['passed'])}</td></tr>"
        )
    table = (
        "<div class='tablewrap'><table><tr><th>Sample</th><th>Well</th><th>Type</th>"
        "<th>Conc ng/uL</th><th>Mass ng</th><th></th></tr>" + "".join(rows) + "</table></div>"
    )
    uni = data.get("uniformity_cv_percent")
    bits = [f"standard curve R-squared {_esc(data.get('curve_r2'))}",
            f"dilution {_esc(data.get('dilution_factor'))}x"]
    if uni is not None:
        bits.append(f"yield uniformity CV {_esc(uni)}%")
    return table + f"<div class='note'>{'; '.join(bits)}.</div>"


def _pcr_enrichment_body(data: dict) -> str:
    anneal = data.get("pcr1_anneal_c")
    anneal_txt = f"{anneal} C" if anneal is not None else "not supplied"
    return (
        "<div class='kv'>"
        f"<div class='k'>Target</div><div class='v'>{_esc(data.get('target'))} ({_esc(data.get('target_product_bp'))} bp)</div>"
        f"<div class='k'>PCR1</div><div class='v'>{_esc(data.get('pcr1_program'))}, anneal {_esc(anneal_txt)}</div>"
        f"<div class='k'>PCR2</div><div class='v'>{_esc(data.get('pcr2_program'))}, {_esc(data.get('pcr2_cycles'))} cycles</div>"
        f"<div class='k'>SPRI post-PCR1</div><div class='v mono'>{_esc(data.get('spri_post_pcr1'))}</div>"
        f"<div class='k'>SPRI post-PCR2</div><div class='v mono'>{_esc(data.get('spri_post_pcr2'))}</div>"
        "</div>"
        f"<div class='note'>{_esc(data.get('pcr1_note',''))}</div>"
    )


def _handoff_body(data: dict) -> str:
    pool_rows = []
    for p in data.get("pooling", []):
        pool_rows.append(
            f"<tr><td>{_esc(p['sample_id'])}</td><td>{_esc(p['well'])}</td>"
            f"<td class='num'>{_esc(p['concentration_ng_per_ul'])}</td>"
            f"<td class='num'>{_esc(p['volume_to_pool_ul'])}</td></tr>"
        )
    pool_table = (
        "<div class='tablewrap'><table><tr><th>Library</th><th>Well</th>"
        "<th>Conc ng/uL</th><th>Pool uL</th></tr>" + "".join(pool_rows) + "</table></div>"
    )
    kv = (
        "<div class='kv'>"
        f"<div class='k'>Expected final size</div><div class='v mono'>{_esc(data.get('expected_final_bp'))} bp</div>"
        f"<div class='k'>Assay / analysis</div><div class='v'>{_esc(data.get('analysis_intent'))}</div>"
        "</div>"
    )
    csv = data.get("samplesheet_csv", "")
    sheet = f"<h2 style='margin-top:8px'>Sequencing sample sheet</h2><pre>{_esc(csv)}</pre>" if csv else ""
    return kv + "<h2 style='margin-top:8px'>Equal-mass pooling</h2>" + pool_table + sheet


_BODY = {
    "lh_qc": _lh_qc_body,
    "wgs_prep": _wgs_prep_body,
    "qc_post_wgs_prep": _fluorescent_dsdna_body,
    "qc_post_pcr_enrichment": _fluorescent_dsdna_body,
    "pcr_enrichment": _pcr_enrichment_body,
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
        body += f"<div class='note'><b>Dropped here:</b> {_esc(dropped)} (did not meet the gate).</div>"

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
        f"<span class='chip{' amber' if k in ('calibrate',) else ' red' if k=='todo' else ''}'>"
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

    survivors = ", ".join(outcome.final_active_sample_ids) or "none"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sequencing-validation dossier - {_esc(cfg.run_id)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
  <div class="eyebrow">Sequencing-validation package</div>
  <h1>{_esc(cfg.run_id)}</h1>
  <p class="sub">WGS preparation + PCR enrichment, QC-gated, for confirming {_esc(cfg.assay_type.value.replace('_',' '))} at {_esc(cfg.target.name)}.</p>
  <div class="meta">
    <span>Operator <b>{_esc(cfg.operator)}</b></span>
    <span>Mode <b>{_esc(cfg.mode.value)}</b></span>
    <span>Target <b>{_esc(cfg.target.name)} ({_esc(cfg.target.target_product_bp)} bp)</b></span>
    <span>Run at <b>{_esc(outcome.timestamp or 'n/a')}</b></span>
    <span>{_status_badge(outcome.status)}</span>
  </div>
  <p class="sub" style="margin-top:10px">{_esc(outcome.message)}. Survivors to sequencing: <b>{_esc(survivors)}</b>.</p>
  <div class="chips">{guard_chips}</div>
  {blocking}
  <div class="flow">{''.join(flow)}</div>
  <div class="foot">di-omics &#183; plr-tested &#183; sequencing-validation</div>
</div></body></html>"""
