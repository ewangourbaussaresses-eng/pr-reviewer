"""Analyse d'un diff de pull request : fichiers, lignes ajoutées, règles statiques."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SEVERITIES = {"error": 3, "warning": 2, "info": 1}


@dataclass
class AddedLine:
    path: str
    number: int
    text: str


@dataclass
class ParsedDiff:
    files: list[str] = field(default_factory=list)
    added: list[AddedLine] = field(default_factory=list)
    removed: int = 0

    @property
    def summary(self) -> str:
        return f"{len(self.files)} fichier(s), {len(self.added)} ligne(s) ajoutée(s)"


@dataclass
class Finding:
    path: str
    line: int
    severity: str
    rule: str
    message: str
    suggestion: str = ""
    source: str = "rules"

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "severity": self.severity,
                "rule": self.rule, "message": self.message,
                "suggestion": self.suggestion, "source": self.source}


# (rule, sévérité, motif, message, suggestion, extensions concernées)
RULES: list[tuple[str, str, str, str, str, set[str] | None]] = [
    ("secret", "error",
     r"(?i)(api[_-]?key|secret|token|password|passwd|mot_de_passe)\s*[:=]\s*"
     r"['\"][^'\"]{8,}['\"]",
     "Secret potentiellement en clair dans le code.",
     "Utilisez une variable d'environnement ou un secret CI ; ne commitez jamais de clé.", None),
    ("eval", "error", r"\beval\s*\(", "Appel à eval() : exécution de code arbitraire.",
     "Remplacez par une analyse explicite (json.loads, ast.literal_eval, dispatch).", None),
    ("exec", "error", r"\bexec\s*\(", "Appel à exec() : exécution de code arbitraire.",
     "Évitez exec() ; préférez une table de fonctions.", None),
    ("sql", "error",
     r"(?i)(execute|query)\s*\(\s*(f['\"]|['\"].*%\s*\(|['\"].*\+\s*)",
     "Requête SQL construite par concaténation / f-string.",
     "Utilisez des requêtes paramétrées (curseur.execute(sql, params)).", None),
    ("shell", "error",
     r"subprocess\.(run|call|Popen)\s*\([^)]*shell\s*=\s*True",
     "shell=True avec subprocess : injection de commande possible.",
     "Passez une liste d'arguments et laissez shell=False.", {".py"}),
    ("yaml", "warning", r"yaml\.load\s*\([^)]*\)(?!\s*,\s*Loader)",
     "yaml.load sans Loader explicite.",
     "Utilisez yaml.safe_load().", {".py"}),
    ("pickle", "warning", r"\bpickle\.loads?\s*\(",
     "Désérialisation pickle : dangereuse sur des données non fiables.",
     "Préférez json pour des données externes.", {".py"}),
    ("bare-except", "warning", r"except\s*:",
     "except nu : masque toutes les erreurs, y compris KeyboardInterrupt.",
     "Capturez une exception précise (except ValueError:).", {".py"}),
    ("mutable-default", "warning",
     r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\})",
     "Argument mutable par défaut : partagé entre les appels.",
     "Utilisez None par défaut puis créez la liste/dict dans la fonction.", {".py"}),
    ("print", "info", r"^\s*print\s*\(", "print() laissé dans le code.",
     "Utilisez le module logging.", {".py"}),
    ("todo", "info", r"(?i)\b(TODO|FIXME|XXX)\b", "Marqueur TODO/FIXME ajouté.",
     "Ouvrez une issue ou complétez avant fusion.", None),
    ("var", "warning", r"^\s*var\s+\w+", "var au lieu de const/let.",
     "Utilisez const (ou let si réassigné).", {".js", ".ts", ".jsx", ".tsx"}),
    ("console", "info", r"console\.(log|debug)\s*\(", "console.log laissé dans le code.",
     "Retirez avant fusion ou utilisez un logger.", {".js", ".ts", ".jsx", ".tsx"}),
    ("innerhtml", "error", r"\.innerHTML\s*=", "innerHTML : risque d'injection HTML/XSS.",
     "Utilisez textContent, ou nettoyez l'entrée.", {".js", ".ts", ".jsx", ".tsx", ".html"}),
    ("http", "warning", r"http://(?!localhost|127\.0\.0\.1)",
     "URL en HTTP non chiffré.", "Passez en HTTPS.", None),
    ("debug", "warning", r"(?i)(debug\s*=\s*True|app\.run\([^)]*debug\s*=\s*True)",
     "Mode debug activé.", "Désactivez le debug en production.", {".py"}),
    ("timeout", "info",
     r"(requests\.(get|post|put|delete)|urlopen)\s*\([^)]*\)",
     "Appel réseau sans timeout visible.",
     "Ajoutez timeout=… pour éviter un blocage indéfini.", {".py"}),
]


def parse_diff(diff_text: str) -> ParsedDiff:
    parsed = ParsedDiff()
    current_path = ""
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            match = re.match(r"diff --git a/(.*?) b/(.*)$", raw)
            if match:
                current_path = match.group(2)
                parsed.files.append(current_path)
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            if current_path:
                parsed.added.append(AddedLine(current_path, new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            parsed.removed += 1
        elif not raw.startswith("\\"):
            new_line += 1
    return parsed


def _extension(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot != -1 else ""


def analyze_static(parsed: ParsedDiff) -> list[Finding]:
    findings: list[Finding] = []
    for line in parsed.added:
        extension = _extension(line.path)
        for rule, severity, pattern, message, suggestion, extensions in RULES:
            if extensions and extension not in extensions:
                continue
            if re.search(pattern, line.text):
                findings.append(Finding(line.path, line.number, severity, rule,
                                        message, suggestion))
        if len(line.text) > 140:
            findings.append(Finding(line.path, line.number, "info", "long-line",
                                    f"Ligne très longue ({len(line.text)} caractères).",
                                    "Découpez la ligne."))
    return findings


def is_binary_or_generated(path: str) -> bool:
    lowered = path.lower()
    return (lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico",
                              ".woff", ".woff2", ".ttf", ".min.js", ".lock", ".svg"))
            or "package-lock" in lowered or "poetry.lock" in lowered)


def filter_files(parsed: ParsedDiff, max_files: int = 20) -> ParsedDiff:
    keep = [line for line in parsed.added if not is_binary_or_generated(line.path)]
    files = [f for f in parsed.files if not is_binary_or_generated(f)][:max_files]
    return ParsedDiff(files=files, added=[l for l in keep if l.path in files],
                      removed=parsed.removed)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-SEVERITIES.get(f.severity, 0), f.path, f.line))


def counts(findings: list[Finding]) -> dict[str, int]:
    result = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        result[finding.severity] = result.get(finding.severity, 0) + 1
    return result


def should_fail(findings: list[Finding], threshold: str = "error") -> bool:
    """Le job CI doit-il échouer ?"""
    if threshold == "never":
        return False
    limit = SEVERITIES.get(threshold, 3)
    return any(SEVERITIES.get(f.severity, 0) >= limit for f in findings)
