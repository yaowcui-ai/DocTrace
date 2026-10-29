"""Generate an ignored, private deployment config without revealing credentials."""
import argparse
import os
from pathlib import Path
import secrets

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
COPY_ALLOWLIST = ('LIGHTRAG_API_KEY', 'ANSWER_URL', 'ANSWER_MODEL', 'ANSWER_API_KEY',
    'RERANK_URL', 'RERANK_MODEL', 'RERANK_API_KEY')


def _quoted(value):
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError('Configuration values must be single-line text.')
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


def generate(source=ROOT / '.env', target=ROOT / 'runtime/upgrade/.env'):
    source, target = Path(source), Path(target)
    copied = dotenv_values(source, encoding='utf-8', interpolate=False) if source.is_file() else {}
    values = {name: copied[name] for name in COPY_ALLOWLIST if isinstance(copied.get(name), str) and copied[name]}
    values.update(MYSQL_HOST='127.0.0.1', MYSQL_PORT='3310', MYSQL_DATABASE='doctrace_upgrade',
        MYSQL_USER='doctrace_upgrade_app', MYSQL_PASSWORD=secrets.token_urlsafe(32),
        MYSQL_ROOT_PASSWORD=secrets.token_urlsafe(40), UPGRADE_ADMIN_USERNAME='upgrade_admin',
        UPGRADE_ADMIN_PASSWORD=secrets.token_urlsafe(24), AUTH_ALLOWED_ORIGIN='http://127.0.0.1:8005',
        DOCTRACE_SESSION_COOKIE='doctrace_upgrade_session',
        AUTH_COOKIE_SECURE='false', AUTH_SESSION_TTL_SECONDS='7200',
        LIGHTRAG_URL='http://host.docker.internal:9624', HR_LIGHTRAG_URL='http://host.docker.internal:9624',
        HR_CORPUS_ID='gitlab_hr_v3', HR_MAX_TOTAL_TOKENS='40000', CONTEXT_MAX_CHARS='30000', CONTEXT_MIN_SCORE='0.3',
        MANAGED_LIGHTRAG_URL='http://host.docker.internal:9631', MANAGED_LIGHTRAG_API_KEY=secrets.token_urlsafe(32))
    body = '# Private upgrade config. Never commit or print this file.\n' + ''.join(
        name + '=' + _quoted(str(value)) + '\n' for name, value in values.items())
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
        output.write(body)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / '.env')
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/upgrade/.env')
    args = parser.parse_args(argv)
    try:
        target = generate(args.source, args.output)
    except FileExistsError:
        print('Private upgrade configuration already exists; no file was overwritten.')
        return 1
    except (ValueError, OSError):
        print('Could not generate private configuration; no secret values are displayed.')
        return 1
    print('Private configuration created at ' + str(target) + '. Credentials are not displayed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
