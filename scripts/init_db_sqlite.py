#!/usr/bin/env python3
"""Initialize the artifacts SQLite DB (best-practice wrapper).

Usage:
    python scripts/init_db_sqlite.py [path]

Default path: artifacts.db
"""
import sys
from store_artifacts import init_db

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'artifacts.db'
    init_db(path, backend='sqlite')
    print(f'Initialized sqlite DB at {path}')

if __name__ == '__main__':
    main()
