"""Own MySQL upgrade database, real lifecycle, synthetic provider only."""
import os
from pathlib import Path
import sys
import time
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
values = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
if values.get('MYSQL_DATABASE') != 'doctrace_upgrade' or values.get('MYSQL_PORT') != '3310':
    raise RuntimeError('Wrong fixture database')
os.environ.update({key: value for key, value in values.items() if value is not None})
os.environ['AUTH_ALLOWED_ORIGIN'] = 'http://127.0.0.1:' + sys.argv[1]
os.environ['DOCTRACE_SESSION_COOKIE'] = 'doctrace_load_session'

from contextlib import nullcontext
import uvicorn
from app import main
from app.schemas import MediumAskResponse


def synthetic(*args, mode, **kwargs):
    time.sleep(.1)
    return MediumAskResponse(response='Synthetic load answer; no model invoked.', references=[], llm_generated=False,
        retrieval={'mode': mode, 'policy_version': 'synthetic-load', 'strategy': 'offline_fixture', 'degraded': False})


main.make_qa_client = lambda: nullcontext(None)
main.run_selected_qa_pipeline = synthetic
uvicorn.run(main.app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
