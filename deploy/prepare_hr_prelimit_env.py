"""Reuse existing local reranker credentials without displaying or committing them."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.rerank_config import load_rerank_settings

def main():
    settings=load_rerank_settings()
    out=ROOT/'runtime/hr_prelimit';out.mkdir(parents=True,exist_ok=True)
    (out/'cache').mkdir(exist_ok=True)
    # Compose env_file quoting must preserve literal dollar signs and backslashes.
    def quoted(value):
        if "'" in value or '\n' in value or '\r' in value:
            raise ValueError('Unsupported credential quoting; no file written')
        return "'"+value+"'"
    body='\n'.join(k+'='+quoted(v) for k,v in {
        'DOCTRACE_RERANK_URL':settings.rerank_url,
        'DOCTRACE_RERANK_MODEL':settings.rerank_model,
        'DOCTRACE_RERANK_API_KEY':settings.rerank_api_key}.items())+'\n'
    (out/'.env').write_text(body,encoding='utf-8')
    print('Private ignored runtime env prepared; no credential values displayed.')

if __name__=='__main__':main()
