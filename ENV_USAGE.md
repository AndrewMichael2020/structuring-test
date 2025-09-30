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

