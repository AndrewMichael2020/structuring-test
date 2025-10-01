import sys
from pathlib import Path
import runpy


def test_main_batch_cli(monkeypatch, tmp_path):
    # Prepare a urls.txt
    uf = tmp_path / 'urls.txt'
    uf.write_text('# comment\nhttps://a.com/x, https://b.com/y\nhttps://c.com/z\n', encoding='utf-8')

    # Stub batch_extract_accident_info to avoid network
    import accident_info as ai
    monkeypatch.setattr(ai, 'batch_extract_accident_info', lambda urls, batch_size=3: [str(tmp_path / f'{i}.json') for i, _ in enumerate(urls)])

    # Monkeypatch argv and cwd into tmp to avoid writing to repo
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('WRITE_TO_DRIVE', 'false')

    # Run main module; should exit(0)
    import builtins
    exit_codes = {'code': None}

    def fake_exit(code=0):
        exit_codes['code'] = code
        raise SystemExit(code)

    monkeypatch.setattr(sys, 'argv', ['main.py', '--urls-file', str(uf), '--mode', 'text-only'])
    monkeypatch.setattr(sys, 'exit', fake_exit)
    try:
        runpy.run_module('main', run_name='__main__')
    except SystemExit:
        pass

    assert exit_codes['code'] == 0
