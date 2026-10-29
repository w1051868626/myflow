"""Run the full local acceptance gate. Requires installed project dependencies."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', help='Backend Python interpreter (defaults to project environment)')
    args = parser.parse_args()
    candidates = [ROOT / '.conda/python.exe', ROOT / '.conda/bin/python',
                  ROOT / 'backend/.venv/Scripts/python.exe', ROOT / 'backend/.venv/bin/python']
    python = args.python or next((str(path) for path in candidates if path.is_file()), sys.executable)
    node = shutil.which('node')
    if not node:
        parser.error('Node.js 24.19.0+ (24.x) is required on PATH')
    version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
    parts = tuple(map(int, version.split('.')))
    if parts[0] != 24 or parts < (24, 19, 0):
        parser.error(f'Expected Node.js >=24.19.0 <25; found {version}')
    checks = [
        ('Backend acceptance', [python, '-m', 'pytest', '-q'], ROOT / 'backend'),
        ('Frontend acceptance', [node, '--run', 'test'], ROOT / 'frontend'),
        ('TypeScript', [node, '--run', 'typecheck'], ROOT / 'frontend'),
        ('Production build', [node, '--run', 'build'], ROOT / 'frontend'),
    ]
    for name, command, directory in checks:
        print(f'\n>>> {name}', flush=True)
        try:
            subprocess.run(command, cwd=directory, check=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f'FAIL: {name}: {exc}', file=sys.stderr)
            return 1
    print('\nPASS: all four acceptance checks completed.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
