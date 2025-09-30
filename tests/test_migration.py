import json
import tempfile
from pathlib import Path
import subprocess
import sys


def run_script(args, cwd=None):
    cmd = [sys.executable, str(Path('scripts/import_artifacts_to_db.py').resolve())] + args
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return res


def test_migration_dry_run_and_import(tmp_path):
    # create a fake artifacts tree
    base = tmp_path / 'artifacts'
    domain = base / 'example.com' / '20250101_000000'
    domain.mkdir(parents=True)
    artifact = {
        'source_url': 'https://example.com/article/1',
        'extracted_at': '2025-01-01T00:00:00Z',
        'mountain_name': 'Mt. Test',
        'extraction_confidence_score': 0.9,
    }
    p = domain / 'accident_info.json'
    p.write_text(json.dumps(artifact), encoding='utf-8')

    db_path = tmp_path / 'artifacts_db.json'

    # dry-run should not create DB file
    r = run_script(['--artifacts-dir', str(base), '--db-path', str(db_path), '--dry-run'])
    assert r.returncode == 0
    assert '[DRY]' in r.stdout or 'Would import' in r.stdout
    assert not db_path.exists()

    # real run should create DB file (if TinyDB installed) or in-memory file
    r2 = run_script(['--artifacts-dir', str(base), '--db-path', str(db_path)])
    assert r2.returncode == 0
    # DB file may or may not exist depending on TinyDB presence; however the script prints summary
    assert 'Imported' in r2.stdout

    # run again with --skip-existing; this should skip the already-imported artifact
    r3 = run_script(['--artifacts-dir', str(base), '--db-path', str(db_path), '--skip-existing'])
    assert r3.returncode == 0
    # expect skipped count in summary
    assert 'skipped' in r3.stdout.lower()
