"""CLI pr-reviewer : revue locale, ou publication sur la PR dans GitHub Actions."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__, llm
from .analyze import parse_diff, should_fail
from .github_api import fetch_pr_diff, post_comment
from .render import render_annotations, render_comment
from .review import review, summarize_with_llm


def git_diff(base: str, head: str) -> str:
    result = subprocess.run(["git", "diff", f"{base}...{head}"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        result = subprocess.run(["git", "diff", base, head], capture_output=True, text=True)
    return result.stdout


def command_review(args: argparse.Namespace) -> int:
    if args.diff:
        diff_text = Path(args.diff).read_text(encoding="utf-8", errors="replace")
    elif args.pr and not args.diff:
        diff_text = fetch_pr_diff(args.repo, int(args.pr))
    else:
        diff_text = git_diff(args.base, args.head)

    if not diff_text.strip():
        print("ℹ aucun changement à relire")
        return 0

    parsed = parse_diff(diff_text)
    result = review(parsed, use_llm=not args.no_llm)
    findings = result["findings"]

    summary = None
    if findings and not args.no_llm and llm.is_available():
        summary = summarize_with_llm(findings, parsed)

    comment = render_comment(result, summary=summary)

    if args.annotations:
        print(render_annotations(findings))
    if args.json:
        print(json.dumps({"engine": result["engine"], "counts": result["counts"],
                          "summary": summary, "comment": comment,
                          "findings": [f.as_dict() for f in findings]},
                         ensure_ascii=False, indent=2))
    elif not args.annotations:
        print(comment)

    if args.out:
        Path(args.out).write_text(comment, encoding="utf-8")

    if args.comment and args.pr:
        repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
        if not repo:
            print("✖ --comment nécessite --repo ou GITHUB_REPOSITORY", file=sys.stderr)
            return 2
        outcome = post_comment(repo, int(args.pr), comment, dry_run=args.dry_run)
        if outcome.get("dry_run"):
            print("ℹ simulation : commentaire non publié", file=sys.stderr)
        else:
            print(f"✔ commentaire {'mis à jour' if outcome.get('updated') else 'publié'} : "
                  f"{outcome.get('url')}", file=sys.stderr)

    if args.fail_on != "never" and should_fail(findings, args.fail_on):
        return 1
    return 0


def command_llm(args: argparse.Namespace) -> int:
    info = llm.status()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print(f"Fournisseur : {info['provider']} "
          f"({'connecté' if info['available'] else 'non configuré'})")
    if info["model"]:
        print(f"Modèle      : {info['model']}")
    if not info["available"]:
        print("→ Sans clé, seules les règles statiques sont appliquées.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-reviewer",
        description="Relit un diff de pull request et commente la PR sur GitHub.")
    parser.add_argument("--version", action="version", version=f"pr-reviewer {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    rev = sub.add_parser("review", help="analyser un diff")
    rev.add_argument("--diff", help="fichier .diff à analyser")
    rev.add_argument("--base", default="origin/main", help="branche de base")
    rev.add_argument("--head", default="HEAD", help="branche à relire")
    rev.add_argument("--repo", help="owner/name (défaut : GITHUB_REPOSITORY)")
    rev.add_argument("--pr", help="numéro de pull request")
    rev.add_argument("--comment", action="store_true", help="publier le commentaire sur la PR")
    rev.add_argument("--dry-run", action="store_true", help="ne rien publier")
    rev.add_argument("--no-llm", action="store_true", help="règles statiques seulement")
    rev.add_argument("--annotations", action="store_true", help="sortie GitHub ::error/::warning")
    rev.add_argument("--fail-on", choices=["error", "warning", "info", "never"],
                     default="error", help="seuil d'échec du job (défaut : error)")
    rev.add_argument("--json", action="store_true")
    rev.add_argument("--out", help="écrire le commentaire Markdown dans un fichier")
    rev.set_defaults(func=command_review)

    llm_cmd = sub.add_parser("llm", help="état du connecteur IA")
    llm_cmd.add_argument("--json", action="store_true")
    llm_cmd.set_defaults(func=command_llm)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
