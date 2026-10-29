"""Run a check with an immutable command, exit code and UTF-8 log (no shell)."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or re.search(r'(?i)\b(?:api_key|password|token)\s*=', ' '.join(command)):
        parser.error('Provide a command without inline credentials.')
    now = datetime.now(timezone.utc)
    folder = ROOT / 'evaluation' / 'upgrade' / (now.strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    folder.mkdir(parents=True)
    report = {'label': args.label, 'command': command, 'started_at': now.isoformat(), 'exit_code': None}
    (folder / 'command.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    started = time.perf_counter()
    with (folder / 'output.log').open('wb') as output:
        process = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, shell=False,
                                 env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    report.update(exit_code=process.returncode, seconds=round(time.perf_counter()-started, 3),
                  finished_at=datetime.now(timezone.utc).isoformat())
    (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Report:', folder)
    print('Exit:', process.returncode)
    print((folder / 'output.log').read_text(encoding='utf-8', errors='replace')[-1800:])
    return process.returncode


if __name__ == '__main__':
    sys.exit(main())
