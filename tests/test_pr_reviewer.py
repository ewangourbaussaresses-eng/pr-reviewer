"""Tests pr-reviewer — aucun appel réseau, GitHub et LLM simulés."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pr_reviewer import github_api, llm  # noqa: E402
from pr_reviewer.analyze import (analyze_static, counts, filter_files,  # noqa: E402
                                 is_binary_or_generated, parse_diff, should_fail,
                                 sort_findings)
from pr_reviewer.cli import main  # noqa: E402
from pr_reviewer.render import MARKER, render_annotations, render_comment  # noqa: E402
from pr_reviewer.review import review  # noqa: E402

DIFF = """diff --git a/app/auth.py b/app/auth.py
--- a/app/auth.py
+++ b/app/auth.py
@@ -1,3 +1,8 @@
 import os
-import json
+API_KEY = "sk-live-1234567890abcdef"
+def login(user_input):
+    try:
+        return eval(user_input)
+    except:
+        pass
+print("debug")
diff --git a/web/app.js b/web/app.js
--- a/web/app.js
+++ b/web/app.js
@@ -1,2 +1,4 @@
+var token = 1;
+document.getElementById('x').innerHTML = location.hash;
+console.log('hi');
+fetch('http://example.com/api');
"""

CLEAN_DIFF = """diff --git a/lib/math.py b/lib/math.py
--- a/lib/math.py
+++ b/lib/math.py
@@ -1,2 +1,4 @@
+def add(a, b):
+    return a + b
"""


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "OLLAMA_MODEL",
                "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    yield


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #
def test_parse_diff_compte_les_lignes():
    parsed = parse_diff(DIFF)
    assert parsed.files == ["app/auth.py", "web/app.js"]
    assert len(parsed.added) == 11
    assert parsed.removed == 1


def test_parse_diff_numerote_les_lignes():
    parsed = parse_diff(DIFF)
    first = parsed.added[0]
    assert first.path == "app/auth.py"
    assert first.number == 2


def test_regles_secret_et_eval():
    findings = analyze_static(parse_diff(DIFF))
    rules = {f.rule for f in findings}
    assert "secret" in rules
    assert "eval" in rules
    assert "bare-except" in rules
    assert "print" in rules


def test_regles_javascript():
    findings = analyze_static(parse_diff(DIFF))
    rules = {f.rule for f in findings}
    assert "var" in rules
    assert "innerhtml" in rules
    assert "console" in rules
    assert "http" in rules


def test_diff_propre_ne_declenche_rien():
    assert analyze_static(parse_diff(CLEAN_DIFF)) == []


def test_severites_et_tri():
    findings = sort_findings(analyze_static(parse_diff(DIFF)))
    assert findings[0].severity == "error"


def test_comptage_et_seuil():
    findings = analyze_static(parse_diff(DIFF))
    counted = counts(findings)
    assert counted["error"] >= 2
    assert should_fail(findings, "error") is True
    assert should_fail(findings, "never") is False
    assert should_fail([], "error") is False


def test_fichiers_generes_ignores():
    assert is_binary_or_generated("image.png")
    assert is_binary_or_generated("package-lock.json")
    assert is_binary_or_generated("app.min.js")
    assert not is_binary_or_generated("app.py")


def test_filter_files_retire_les_binaires():
    diff = """diff --git a/logo.png b/logo.png
--- a/logo.png
+++ b/logo.png
@@ -1 +1 @@
+binaire
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
+print("x")
"""
    filtered = filter_files(parse_diff(diff))
    assert filtered.files == ["app.py"]


def test_ligne_trop_longue():
    long_line = "x = '" + "a" * 200 + "'"
    diff = f"""diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
+{long_line}
"""
    assert any(f.rule == "long-line" for f in analyze_static(parse_diff(diff)))


# --------------------------------------------------------------------------- #
# Revue complète
# --------------------------------------------------------------------------- #
def test_review_sans_ia():
    result = review(parse_diff(DIFF))
    assert result["engine"] == "rules"
    assert result["counts"]["error"] >= 2


def test_review_avec_ia_simulee(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: [
        {"line": 50, "severity": "warning", "message": "Cas limite non géré.",
         "suggestion": "Ajoutez un test."}])
    result = review(parse_diff(DIFF))
    assert result["engine"] == "rules+llm"
    assert any(f.source == "llm" for f in result["findings"])


def test_review_ia_dedoublonne_les_lignes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: [
        {"line": 2, "severity": "error", "message": "Doublon", "suggestion": ""}])
    result = review(parse_diff(DIFF))
    keys = [(f.path, f.line) for f in result["findings"]]
    assert len(keys) == len(set(keys))


def test_review_repli_si_ia_indisponible(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: None)
    assert review(parse_diff(DIFF))["engine"] == "rules"


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #
def test_render_contient_le_marqueur():
    comment = render_comment(review(parse_diff(DIFF)))
    assert MARKER in comment
    assert "app/auth.py" in comment
    assert "🔴" in comment


def test_render_aucun_probleme():
    comment = render_comment(review(parse_diff(CLEAN_DIFF)))
    assert "Aucun problème détecté" in comment


def test_render_resume_personnalise():
    comment = render_comment(review(parse_diff(DIFF)), summary="Deux erreurs bloquantes.")
    assert "Deux erreurs bloquantes." in comment


def test_render_limite_le_nombre():
    result = review(parse_diff(DIFF))
    comment = render_comment(result, max_findings=1)
    assert "non affichée" in comment


def test_annotations_github():
    findings = analyze_static(parse_diff(DIFF))
    annotations = render_annotations(findings)
    assert "::error file=app/auth.py,line=2::" in annotations


# --------------------------------------------------------------------------- #
# GitHub (simulé)
# --------------------------------------------------------------------------- #
def test_post_comment_dry_run():
    outcome = github_api.post_comment("o/r", 1, "texte", dry_run=True)
    assert outcome["dry_run"] is True


def test_post_comment_sans_token():
    with pytest.raises(RuntimeError):
        github_api.post_comment("o/r", 1, "texte")


def test_post_comment_cree_puis_met_a_jour(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    calls = []

    def fake_request(method, url, payload=None):
        calls.append((method, url))
        if method == "GET":
            return []
        return {"id": 7, "html_url": "https://x/7"}

    monkeypatch.setattr(github_api, "_request", fake_request)
    outcome = github_api.post_comment("o/r", 3, "corps")
    assert outcome["created"] is True
    assert calls[0][0] == "GET" and calls[-1][0] == "POST"


def test_post_comment_met_a_jour_existant(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def fake_request(method, url, payload=None):
        if method == "GET":
            return [{"id": 9, "body": MARKER + " ancien"}]
        return {"id": 9, "html_url": "https://x/9"}

    monkeypatch.setattr(github_api, "_request", fake_request)
    outcome = github_api.post_comment("o/r", 3, "corps")
    assert outcome["updated"] is True


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_review_depuis_fichier(tmp_path: Path, capsys):
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(DIFF, encoding="utf-8")
    code = main(["review", "--diff", str(diff_file), "--no-llm", "--json"])
    assert code == 1  # erreurs présentes → échec
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["error"] >= 2


def test_cli_review_diff_propre(tmp_path: Path, capsys):
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(CLEAN_DIFF, encoding="utf-8")
    assert main(["review", "--diff", str(diff_file), "--no-llm", "--json"]) == 0


def test_cli_fail_on_never(tmp_path: Path, capsys):
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(DIFF, encoding="utf-8")
    assert main(["review", "--diff", str(diff_file), "--no-llm",
                 "--fail-on", "never", "--json"]) == 0


def test_cli_ecrit_le_commentaire(tmp_path: Path, capsys):
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(DIFF, encoding="utf-8")
    out = tmp_path / "comment.md"
    main(["review", "--diff", str(diff_file), "--no-llm", "--out", str(out),
          "--fail-on", "never"])
    assert MARKER in out.read_text(encoding="utf-8")


def test_cli_annotations(tmp_path: Path, capsys):
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(DIFF, encoding="utf-8")
    main(["review", "--diff", str(diff_file), "--no-llm", "--annotations",
          "--fail-on", "never"])
    assert "::error" in capsys.readouterr().out


def test_cli_comment_sans_repo(tmp_path: Path, capsys):
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(CLEAN_DIFF, encoding="utf-8")
    code = main(["review", "--diff", str(diff_file), "--no-llm", "--comment", "--pr", "1"])
    assert code == 2


def test_cli_llm(capsys):
    assert main(["llm"]) == 0
    assert "Fournisseur" in capsys.readouterr().out
