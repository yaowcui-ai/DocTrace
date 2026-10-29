"""Whitelist-copy reviewed source/evidence to an existing isolated release branch."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    target = args.target.resolve()
    expected = (ROOT.parent/'output/DocTrace-public-20261021').resolve()
    if target != expected or not (target/'.git').is_dir():
        raise ValueError('Only the explicitly reviewed release checkout is allowed')
    branch = subprocess.check_output(['git', '-C', str(target), 'branch', '--show-current'], text=True).strip()
    if branch != 'codex/doctrace-fullstack-upgrade':
        raise ValueError('Refusing to package into another branch')
    paths = set()
    def add(pattern):
        for path in ROOT.glob(pattern):
            if path.is_file() and not any(part in {'__pycache__', 'node_modules', 'dist', 'test-results', 'playwright-report'} for part in path.parts):
                paths.add(path)
    for pattern in ('app/**/*.py', 'tests/**/*.py', 'scripts/*.py', 'scripts/*.ps1',
                    'frontend/src/**/*', 'frontend/tests/**/*', 'frontend/*.json', 'frontend/*.ts', 'frontend/index.html', 'frontend/README.md',
                    'docs/*UPGRADE*.md', 'docs/ARCHITECTURE.md', 'docs/EXPERIMENT_DESIGN.md', 'docs/EVALUATION_REPORT.md',
                    'docs/ENGINEERING_TEST_REPORT.md', 'docs/BUSINESS_VALUE.md', 'docs/RESUME_EVIDENCE.md',
                    'docs/operations/upgrade-deployment.md', 'docs/operations/managed-knowledge.md',
                    'docs/superpowers/plans/2026-10-28-fullstack-upgrade.md',
                    'evaluation/upgrade_dataset/**/*.json', 'evaluation/upgrade/reports/*.json',
                    '.github/workflows/*.yml'):
        add(pattern)
    for name in ('README.md', 'THIRD_PARTY_NOTICES.md', '.env.example', '.lightrag.env.example', '.dockerignore',
                 'Dockerfile.upgrade', 'pytest.ini', 'requirements.txt', 'requirements-dev.txt', 'requirements-lock.txt',
                 'requirements-benchmark.txt', 'requirements-corpus.txt',
                 'deploy/compose.upgrade.yml', 'deploy/compose.hr-managed.yml', 'deploy/compose.upgrade-probe.yml',
                 'evaluation/diagnostics/20261016T044508Z_38dfaa7a_utils.py.txt', 'evaluation/diagnostics/LightRAG.LICENSE'):
        add(name)
    for folder in (ROOT/'evaluation/upgrade').glob('20*'):
        if folder.is_dir():
            names = ('command.json', 'result.json', 'output.log', 'audit.json', 'operate.patch')
            if '_deployment_' in folder.name:
                names += ('report.json',)
            for name in names:
                path = folder/name
                if path.is_file():
                    paths.add(path)
    # Actual credentials only; placeholder test strings are not deployment secrets.
    secrets = []
    for config in (ROOT/'.env', ROOT/'runtime/upgrade/.env', ROOT.parent/'LightRAG/.env'):
        if config.is_file():
            for key, value in dotenv_values(config, interpolate=False).items():
                if value and len(value) >= 12 and any(word in key.upper() for word in ('API_KEY', 'PASSWORD', 'TOKEN')):
                    secrets.append(value.encode())
    for path in paths:
        body = path.read_bytes()
        if any(secret in body for secret in secrets):
            raise ValueError('Actual private credential detected in: '+path.relative_to(ROOT).as_posix())
    manifest = {}
    for path in sorted(paths):
        relative = path.relative_to(ROOT)
        dest = target/relative
        if not dest.resolve().is_relative_to(target):
            raise ValueError('Unexpected destination')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        manifest[relative.as_posix()] = hashlib.sha256(dest.read_bytes()).hexdigest()
    # Keep Pages, curated legacy deployment and all existing secret exclusions.
    if '# Upgrade generated/private runtime' not in (target/'.gitignore').read_text(encoding='utf-8'):
        with (target/'.gitignore').open('a', encoding='utf-8') as stream:
            stream.write('\n# Upgrade generated/private runtime\nfrontend/dist/\nfrontend/test-results/\nfrontend/playwright-report/\nevaluation/upgrade/new_retrieval/\nevaluation/upgrade/live/\nevaluation/upgrade/generation/\nevaluation/upgrade/performance/\n')
    (target/'.gitattributes').write_text('* text=auto eol=lf\n*.png binary\n*.jpg binary\n*.pdf binary\n*.docx binary\nevaluation/diagnostics/* -text whitespace=-blank-at-eol\n*.patch -text whitespace=-blank-at-eol\n', encoding='utf-8')
    (target/'verification/upgrade-source-manifest.json').write_text(json.dumps({
        'branch': branch, 'files_sha256': manifest,
        'hash_scope': 'Copied working-tree bytes before Git text normalization; frozen algorithm Git bytes are checked separately.',
        'actual_secret_scan': 'passed',
        'excluded': ['private configuration', 'runtime indexes', 'personal history', 'raw candidate batches', 'database backups'],
        'pages_assets_preserved': True}, indent=2), encoding='utf-8')
    print('Packaged reviewed files:', len(paths), 'Actual credential scan: passed; Pages assets retained.')


if __name__ == '__main__':
    main()
