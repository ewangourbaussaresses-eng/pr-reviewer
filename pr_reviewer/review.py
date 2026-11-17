"""Revue par IA : un appel par fichier modifié, réponse JSON structurée."""
from __future__ import annotations

from typing import Any

from . import llm
from .analyze import Finding, ParsedDiff, filter_files

SYSTEM = (
    "Tu es un développeur senior bienveillant qui relit une pull request. Tu signales "
    "les vrais problèmes : bugs logiques, failles de sécurité, cas limites oubliés, "
    "erreurs de gestion d'erreur. Tu ne commentes pas le style quand il est correct, tu "
    "ne reformules pas ce que fait le code, tu ne félicites pas. Maximum 5 remarques par "
    "fichier, les plus importantes d'abord. Tu réponds UNIQUEMENT en JSON, en français."
)

MAX_LINES_PER_FILE = 120


def _diff_for_file(parsed: ParsedDiff, path: str) -> str:
    lines = [f"{line.number:>4} + {line.text}" for line in parsed.added if line.path == path]
    return "\n".join(lines[:MAX_LINES_PER_FILE])


def review_with_llm(parsed: ParsedDiff, max_files: int = 6) -> list[Finding] | None:
    """Remarques du modèle. None si l'IA est indisponible ou échoue partout."""
    subset = filter_files(parsed, max_files=max_files)
    if not subset.files:
        return None

    findings: list[Finding] = []
    answered = False
    for path in subset.files:
        excerpt = _diff_for_file(subset, path)
        if not excerpt.strip():
            continue
        prompt = f"""Voici les lignes ajoutées d'un fichier dans une pull request.

Fichier : {path}
Lignes ajoutées (numérotées) :
{excerpt}

Cherche : bugs, failles (injection, secret, XSS, path traversal), cas limites,
gestion d'erreur manquante, ressources non libérées.
Ignore : formatage, goût personnel, renommage.

Réponds uniquement avec ce JSON :
[{{"line": 12, "severity": "error|warning|info",
   "message": "le problème, une phrase",
   "suggestion": "la correction concrète, une phrase"}}]
Si rien de sérieux : []"""
        data = llm.ask_json(prompt, system=SYSTEM, max_tokens=900, temperature=0.2)
        if data is None:
            continue
        answered = True
        if not isinstance(data, list):
            continue
        for item in data[:5]:
            if not isinstance(item, dict) or not item.get("message"):
                continue
            severity = item.get("severity")
            if severity not in ("error", "warning", "info"):
                severity = "warning"
            try:
                line_number = int(item.get("line") or 0)
            except (TypeError, ValueError):
                line_number = 0
            findings.append(Finding(
                path=path, line=line_number, severity=severity, rule="llm",
                message=str(item["message"]).strip()[:400],
                suggestion=str(item.get("suggestion", "")).strip()[:400],
                source="llm"))

    return findings if answered else None


def summarize_with_llm(findings: list[Finding], parsed: ParsedDiff) -> str | None:
    if not findings:
        return None
    payload = [{"path": f.path, "line": f.line, "severity": f.severity,
                "message": f.message} for f in findings[:20]]
    prompt = f"""Résume cette revue de pull request en 2 phrases maximum, en français,
sur un ton professionnel et direct (pas de flatterie).

Fichiers : {', '.join(parsed.files[:10])}
Remarques : {payload}

Réponds uniquement avec le texte du résumé."""
    response = llm.complete_or_none(prompt, system=SYSTEM, max_tokens=200, temperature=0.3)
    return response.text.strip() if response else None


def review(parsed: ParsedDiff, use_llm: bool = True) -> dict[str, Any]:
    """Revue complète : règles statiques + IA si disponible."""
    from .analyze import analyze_static, counts, sort_findings

    static = analyze_static(parsed)
    llm_findings: list[Finding] = []
    engine = "rules"
    if use_llm and llm.is_available():
        result = review_with_llm(parsed)
        if result is not None:
            llm_findings = result
            engine = "rules+llm"

    # dédoublonnage : une remarque IA sur la même ligne qu'une règle est redondante
    static_keys = {(f.path, f.line) for f in static}
    merged = static + [f for f in llm_findings if (f.path, f.line) not in static_keys]
    merged = sort_findings(merged)
    return {"findings": merged, "counts": counts(merged), "engine": engine,
            "summary_line": parsed.summary}
