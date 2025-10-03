# Environment file usage

This project supports storing secrets in a local `.env` file (not committed).

Steps:

1. Copy the example file:

   cp .env.example .env

2. Open `.env` and add your OpenAI API key:

   OPENAI_API_KEY=sk-...your-key-here...

3. Run scripts as usual (they will read the `OPENAI_API_KEY` from the environment).

Security note:

- Do NOT commit a real API key to the repository. This project includes a `.env.example` file you can copy to `.env` for local development, but never commit `.env`.
- For CI / deployment, store sensitive keys (like `OPENAI_API_KEY`) in your repository or organization secrets (GitHub Secrets) and reference them in workflows. Rotate any leaked keys immediately.

If a key was accidentally committed, remove it from the repo, rotate the secret in the provider (OpenAI/GCP), and then update your GitHub Secrets. This repository's `.gitignore` already ignores `.env` files.

Notes:
- `.env` is listed in `.gitignore` to avoid accidental commits.
- If you prefer to export the variable in your shell instead of a `.env` file, that's fine too:

  export OPENAI_API_KEY=sk-...your-key-here...


Import example
----------------
After collecting artifacts you can import them into the SQLite artifacts DB with:

```bash
python scripts/import_artifacts_to_db.py --artifacts-dir artifacts --db-path artifacts.db --dry-run
```

Remove `--dry-run` to perform the actual import. Use `--skip-existing` to avoid re-importing artifacts already present in the DB.

