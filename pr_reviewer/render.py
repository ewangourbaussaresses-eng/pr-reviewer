"""Rendu du commentaire de pull request (Markdown)."""
from __future__ import annotations

from typing import Any

from .analyze import Finding

ICONS = {"error": "🔴", "warning": "🟠", "info": "🔵"}
LABELS = {"error": "erreur", "warning": "avertissement", "info": "remarque"}
MARKER = "<!-- pr-reviewer -->"


def render_comment(result: dict[str, Any], summary: str | None = None,
                   max_findings: int = 30) -> str:
    findings: list[Finding] = result["findings"]
    counts = result["counts"]
    engine = result.get("engine", "rules")

    lines = [MARKER, "## 🤖 Revue automatique", ""]

    if summary:
        lines += [summary, ""]
    elif not findings:
        lines += ["Aucun problème détecté sur les lignes ajoutées. ✅", ""]
    else:
        parts = []
        if counts.get("error"):
            parts.append(f"{counts['error']} erreur(s)")
        if counts.get("warning"):
            parts.append(f"{counts['warning']} avertissement(s)")
        if counts.get("info"):
            parts.append(f"{counts['info']} remarque(s)")
        lines += [f"**{', '.join(parts)}** sur {result.get('summary_line', '')}.", ""]

    if findings:
        by_file: dict[str, list[Finding]] = {}
        for finding in findings:
            by_file.setdefault(finding.path, []).append(finding)
        shown = 0
        for path, items in by_file.items():
            if shown >= max_findings:
                break
            lines += [f"### `{path}`", ""]
            for finding in items:
                if shown >= max_findings:
                    break
                icon = ICONS.get(finding.severity, "•")
                location = f"L{finding.line}" if finding.line else "—"
                lines.append(f"- {icon} **{location}** · {finding.message}")
                if finding.suggestion:
                    lines.append(f"  ↳ *{finding.suggestion}*")
                shown += 1
            lines.append("")
        if len(findings) > shown:
            lines += [f"*… et {len(findings) - shown} autre(s) remarque(s) non affichée(s).*", ""]

    lines += ["---", f"<sub>pr-reviewer · moteur : {engine} · "
                     "aucune modification automatique du code</sub>"]
    return "\n".join(lines)


def render_annotations(findings: list[Finding]) -> str:
    """Commandes GitHub Actions ::error/::warning file=…,line=…"""
    lines = []
    for finding in findings:
        level = {"error": "error", "warning": "warning"}.get(finding.severity, "notice")
        message = finding.message.replace("\n", " ")
        if finding.suggestion:
            message += f" — {finding.suggestion}"
        location = f"file={finding.path}" + (f",line={finding.line}" if finding.line else "")
        lines.append(f"::{level} {location}::{message}")
    return "\n".join(lines)
