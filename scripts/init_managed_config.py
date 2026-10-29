"""Copy only existing supplier bindings into an isolated, private LightRAG config."""
import os
import argparse
import sys
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent/'LightRAG/.env')
    args = parser.parse_args()
    target = ROOT/'runtime/upgrade/managed-lightrag.env'
    if target.exists():
        print('Private managed config exists; no file overwritten.')
        return
    if not args.source.is_file():
        raise SystemExit('Supplier config missing. Pass --source .lightrag.env after filling the example privately.')
    source = dotenv_values(args.source, interpolate=False)
    app = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
    key = app.get('MANAGED_LIGHTRAG_API_KEY')
    if not key:
        raise SystemExit('Generate the private upgrade config first.')
    values = {name: value for name, value in source.items() if value is not None
              and (name.startswith(('LLM_', 'EMBEDDING_')) or name in (
                  'OPENAI_LLM_EXTRA_BODY', 'CHUNK_SIZE', 'CHUNK_OVERLAP_SIZE', 'MAX_TOTAL_TOKENS', 'RERANK_BY_DEFAULT'))}
    if not all(values.get(name) for name in ('LLM_BINDING', 'LLM_MODEL', 'EMBEDDING_BINDING', 'EMBEDDING_MODEL')):
        raise SystemExit('Supplier model bindings are incomplete; private target was not created.')
    values['LIGHTRAG_API_KEY'] = key
    target.parent.mkdir(parents=True, exist_ok=True)
    from scripts.init_upgrade_config import _quoted
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(f'{name}={_quoted(value)}' for name, value in values.items())+'\n')
    print('Isolated managed supplier config created; no credentials displayed.')


if __name__ == '__main__':
    main()
