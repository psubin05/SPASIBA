"""Run Python tests and script-level simulator tests without shell encoding issues."""

from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js is required for simulator script tests.')
    result = subprocess.run([node], input=(ROOT / 'tests/simulator.test.cjs').read_bytes(), cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT / 'server')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
