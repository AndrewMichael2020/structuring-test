# Environment file usage

This project supports storing secrets in a local `.env` file (not committed).

Steps:

1. Copy the example file:

   cp .env.example .env

2. Open `.env` and add your OpenAI API key:

   OPENAI_API_KEY=sk-...your-key-here...

3. Run scripts as usual (they will read the `OPENAI_API_KEY` from the environment).

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

