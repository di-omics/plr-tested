"""Self-contained dossier, run card, and sequencing handoff artifacts."""

from __future__ import annotations

import csv
import html
import io
import json
import os
from typing import Iterable

from .config import SampleType
from .orchestrator import RunOutcome


def _esc(value) -> str:
    return html.escape(str(value))


def render_dossier(outcome: RunOutcome) -> str:
    gate_sections = []
    for gate in outcome.gates:
        rows = []
        for item in gate.run_outcomes:
            measured = "missing" if item.measured is None else item.measured
            rows.append(
                f"<tr><td>{_esc(item.label)}</td><td>{_esc(item.requirement)} {_esc(item.unit)}</td>"
                f"<td>{_esc(measured)}</td><td>{'PASS' if item.passed else 'FAIL'}</td></tr>"
            )
        for verdict in gate.sample_verdicts:
            for item in verdict.outcomes:
                measured = "missing" if item.measured is None else item.measured
                rows.append(
                    f"<tr><td>{_esc(verdict.sample_id)}: {_esc(item.label)}</td>"
                    f"<td>{_esc(item.requirement)} {_esc(item.unit)}</td>"
                    f"<td>{_esc(measured)}</td><td>{'PASS' if item.passed else 'FAIL'}</td></tr>"
                )
        gate_sections.append(
            f"<section><h2>{_esc(gate.gate)} — {_esc(gate.decision.value)}</h2>"
            f"<p>{_esc(gate.message)}</p><table><tr><th>Criterion</th><th>Requirement</th>"
            f"<th>Measured</th><th>Result</th></tr>{''.join(rows)}</table></section>"
        )

    steps = "".join(
        f"<tr><td>{step.number}</td><td>{_esc(step.name)}</td><td>{_esc(step.operation)}</td>"
        f"<td>{_esc(step.reaction_after_ul if step.reaction_after_ul is not None else '')}</td>"
        f"<td>{_esc(step.source)}</td></tr>"
        for step in outcome.protocol
    )
    blockers = "".join(f"<li>{_esc(item)}</li>" for item in outcome.hardware_blockers)
    sample_rows = "".join(
        f"<tr><td>{_esc(sample.id)}</td><td>{_esc(sample.well)}</td>"
        f"<td>{_esc(sample.sample_type.value)}</td><td>{sample.input_ng:g}</td>"
        f"<td>{_esc(sample.control_dilution)}</td><td>{_esc(sample.udi)}</td></tr>"
        for sample in outcome.config.samples
    )
    style = """
    body{font:14px system-ui;margin:32px;color:#17202a;max-width:1200px}h1{margin-bottom:4px}
    h2{margin-top:28px}table{border-collapse:collapse;width:100%;margin:10px 0 18px}
    th,td{border:1px solid #ccd1d1;padding:7px;text-align:left;vertical-align:top}
    th{background:#eef2f3}.badge{display:inline-block;padding:4px 9px;border-radius:12px;background:#e8eef7}
    code{white-space:pre-wrap}.warning{background:#fff4d6;border-left:4px solid #d68910;padding:12px}
    """
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{_esc(outcome.config.run_id)}</title>
<style>{style}</style></head><body>
<h1>methylation-sequencing run dossier</h1>
<p><span class="badge">{_esc(outcome.status.value)}</span> {_esc(outcome.message)}</p>
<table><tr><th>Run</th><th>Operator</th><th>Mode</th><th>Profile</th><th>Method</th></tr>
<tr><td>{_esc(outcome.config.run_id)}</td><td>{_esc(outcome.config.operator)}</td>
<td>{_esc(outcome.config.mode.value)}</td><td>{_esc(outcome.config.profile_kind.value)}</td>
<td>{_esc(outcome.config.method.get("method_name", "operator-configured"))}</td></tr></table>
<h2>Samples</h2><table><tr><th>ID</th><th>Well</th><th>Type</th><th>Input ng</th><th>Controls</th><th>UDI</th></tr>
{sample_rows}</table>
<div class="warning"><b>Hardware status:</b> written/simulation-first; not validated for live sample use.
<ul>{blockers}</ul></div>
{''.join(gate_sections)}
<h2>Sourced protocol plan</h2><table><tr><th>#</th><th>Step</th><th>Operation</th><th>Reaction after (uL)</th><th>Source</th></tr>
{steps}</table>
<p>Research use only. No simulated value is a measurement.</p></body></html>"""


def render_run_card(outcome: RunOutcome) -> str:
    lines = [
        f"# methylation sequencing run card: {outcome.config.run_id}",
        "",
        "Status: candidate plan only; live execution is blocked until every item below is resolved.",
        "",
        "## Hardware blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in outcome.hardware_blockers)
    lines += ["", "## Deck", ""]
    for name, position in outcome.config.deck.positions.items():
        lines.append(f"- `{name}`: rail {position.rail} pos {position.pos} — {position.role}")
    lines += ["", "## Ordered protocol", ""]
    for step in outcome.protocol:
        after = "" if step.reaction_after_ul is None else f" → {step.reaction_after_ul:g} uL"
        lines.append(f"{step.number}. **{step.name}** ({step.operation}){after}")
        if step.note:
            lines.append(f"   - {step.note}")
        if step.simulation_command:
            lines.append(f"   - Safe/offline candidate: `{step.simulation_command}`")
        if step.candidate_hardware_command:
            lines.append(f"   - BLOCKED live candidate: `{step.candidate_hardware_command}`")
    lines += [
        "",
        "## Safety",
        "",
        "Never run unattended. Deck-check every leg, reconcile physical state after any failure, "
        "and keep a person at the E-stop. Only one process may control an instrument.",
    ]
    return "\n".join(lines) + "\n"


def render_samplesheet(outcome: RunOutcome) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Sample_ID", "Well", "UDI", "Input_ng", "Control_DNA_Dilution"])
    passing = set(outcome.final_sample_ids)
    for sample in outcome.config.samples:
        if sample.id in passing and sample.sample_type is not SampleType.PROCESS_BLANK:
            writer.writerow([sample.id, sample.well, sample.udi, f"{sample.input_ng:g}",
                             sample.control_dilution])
    return buffer.getvalue()


def write_artifacts(outcome: RunOutcome, output_root: str) -> str:
    run_dir = os.path.abspath(os.path.join(output_root, outcome.config.run_id))
    os.makedirs(run_dir, exist_ok=True)
    artifacts = {
        "outcome.json": json.dumps(outcome.to_dict(), indent=2, sort_keys=True) + "\n",
        "dossier.html": render_dossier(outcome),
        "run_card.md": render_run_card(outcome),
        "sequencing_samplesheet.csv": render_samplesheet(outcome),
    }
    for name, content in artifacts.items():
        with open(os.path.join(run_dir, name), "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    return run_dir
