# 🔍 pr-reviewer

**Une revue de code automatique sur chaque pull request — dans les règles, sans
blabla.**

À chaque PR ouverte ou mise à jour, `pr-reviewer` lit les lignes ajoutées, détecte les
vraies failles (secret en clair, `eval`, injection SQL, XSS, `shell=True`, `except` nu,
argument mutable par défaut…), demande à une IA de relire les cas limites, puis publie
**un seul commentaire** sur la pull request — mis à jour à chaque push, jamais dupliqué.

Fonctionne **sans clé d'IA** (règles statiques) et **sans dépendance Python**.

---

## Fonctionnalités

- 17 règles statiques : sécurité, robustesse, pièges classiques Python et JavaScript ;
- revue par **IA** (Claude, OpenAI, Ollama local) fichier par fichier, remarques JSON
  structurées, dédoublonnées avec les règles ;
- **un commentaire unique** par PR (marqueur HTML, mis à jour au lieu d'être reposté) ;
- **annotations GitHub** `::error file=…,line=…` visibles dans l'onglet *Files changed* ;
- **seuil d'échec** configurable (`--fail-on error|warning|info|never`) pour bloquer une
  fusion ;
- ignore les fichiers générés (`.lock`, `.min.js`, images) ;
- ton professionnel, aucune flatterie, aucune modification du code.

## Installation

```bash
pip install -e .        # ou : pip install git+https://github.com/<vous>/pr-reviewer.git
```

## Utilisation en local

```bash
# relire la différence entre main et la branche courante
pr-reviewer review --base origin/main --head HEAD --no-llm

# relire un diff déjà exporté
git diff origin/main...HEAD > pr.diff
pr-reviewer review --diff pr.diff

# sortie JSON (pour un autre outil)
pr-reviewer review --diff pr.diff --json
```

Exemple de sortie :

```
**3 erreur(s), 3 avertissement(s), 2 remarque(s)** sur 2 fichier(s), 11 ligne(s) ajoutée(s).

### `app/auth.py`

- 🔴 **L2** · Secret potentiellement en clair dans le code.
  ↳ *Utilisez une variable d'environnement ou un secret CI ; ne commitez jamais de clé.*
- 🔴 **L5** · Appel à eval() : exécution de code arbitraire.
```

## Installation dans un dépôt (GitHub Actions)

Copiez [`action/example-workflow.yml`](action/example-workflow.yml) dans
`.github/workflows/pr-review.yml` de votre dépôt. Il faut :

- `permissions: pull-requests: write` (déjà dans l'exemple) ;
- `GITHUB_TOKEN` : fourni automatiquement par Actions ;
- `ANTHROPIC_API_KEY` *(optionnel)* : secret du dépôt, active la revue par IA.

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
permissions:
  contents: read
  pull-requests: write
```

Le job échoue si une **erreur** est détectée (`--fail-on error`) ; passez
`--fail-on never` pour un mode purement informatif.

## Brancher une IA

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude (recommandé)
export OPENAI_API_KEY="sk-..."          # ou OpenAI
export OLLAMA_MODEL="llama3.2"          # ou Ollama, 100 % local
```

`pr-reviewer llm` affiche le fournisseur détecté. Sans clé, seules les règles
statiques s'appliquent — le commentaire reste utile.

## Limites (à dire franchement)

- Le modèle **ne voit que les lignes ajoutées**, pas tout le fichier : une remarque peut
  manquer de contexte. Les faux positifs existent ; ils sont triés par sévérité pour être
  écartés vite.
- Ce n'est **pas** un analyseur de flux de données : pas de suivi de taint, pas
  d'analyse inter-procédurale. Pour de la sécurité sérieuse, ajoutez CodeQL ou Semgrep.
- Les langages couverts par les règles sont **Python et JavaScript/TypeScript** ; les
  autres fichiers ne sont relus que par l'IA.
- Aucune modification automatique du code : l'outil commente, l'humain décide.

## Tests

```bash
python -m pytest -q     # 30 tests, aucun accès réseau (GitHub et LLM simulés)
```

## Licence

MIT — voir [LICENSE](LICENSE).
