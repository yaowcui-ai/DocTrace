"""Local maintainer tool: publish a reviewed saved QA record, without asking again."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import create_example_draft, publish_example
from .config import ConfigurationError
from .database import create_db_engine
from .database_config import load_database_settings
from .public_example_review import payload_digest
from .public_example_schemas import PublicExampleDraft
from .publish_example_wizard import write_new_json


OUTPUT_DIR = Path(__file__).resolve().parents[1] / 'data/public_examples/from_records'


def read_snapshot(identifier: str) -> dict:
    # This local maintainer command is intentionally not an HTTP endpoint.
    # Copy only public content, never account IDs, logs or retrieval metadata.
    engine = create_db_engine(load_database_settings())
    try:
        with engine.connect() as connection:
            row = connection.execute(text('''
                SELECT question, answer, references_json, corpus_id
                FROM qa_records
                WHERE request_id = :identifier AND status = 'completed' AND http_status = 200
            '''), {'identifier': identifier}).mappings().first()
        if row is None:
            raise ValueError('Record missing or not completed.')
        references = row['references_json']
        if isinstance(references, str):
            references = json.loads(references)
        return PublicExampleDraft.model_validate({
            'question': row['question'], 'answer': row['answer'],
            'corpus_id': row['corpus_id'],
            'references': [{key: ref[key] for key in ('reference_id', 'file_path', 'content')}
                           for ref in references],
        }).model_dump(mode='json')
    finally:
        engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        identifier = str(UUID(input('请输入网页上的问答记录编号：').strip()))
        output = OUTPUT_DIR / (identifier + '.json')
        if any(path.exists() for path in (
            output, output.with_suffix('.review.json'), output.with_suffix('.import.json'),
        )):
            print('该记录已有导出或发布文件，已停止，避免重复创建。')
            print('文件：', output)
            print('可用 app.publish_example --file 加上述路径预览已有发布状态。')
            return 1
        payload = read_snapshot(identifier)
        print('\n===== 即将公开的问题、答案和全部依据 =====')
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print('\n请确认答案正确、条件完整，问题及全部依据均可公开，来源和许可证符合要求。')
        if input('确认审核通过并公开请输入 PUBLISH；其他输入取消：') != 'PUBLISH':
            print('已取消，没有导出、导入或发布。')
            return 0
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        write_new_json(output, payload)
        write_new_json(output.with_suffix('.review.json'), {
            'review_status': 'approved',
            'review_basis': 'maintainer entered PUBLISH after reviewing saved QA snapshot',
            'approved_at_utc': datetime.now(timezone.utc).isoformat(),
            'payload_sha256': payload_digest(payload),
        })
    except (EOFError, KeyboardInterrupt):
        print('\n已取消，没有导入或发布。')
        return 1
    except (ValueError, KeyError, TypeError, OSError, ConfigurationError, SQLAlchemyError):
        print('无法准备公开快照：请检查编号、已完成状态、数据库连接及引用格式。')
        print('未导入或发布；已有本地文件会保留。')
        return 1

    if create_example_draft.main(['--file', str(output), '--submit']) != 0:
        print('导入未确认，已停止。请保留文件和回执，勿反复提交。')
        return 1
    if publish_example.main(['--file', str(output), '--publish']) != 0:
        print('发布未确认，请通过 app.publish_example --file 对导出文件预览核查。')
        return 1
    print('发布成功！刷新主页的“公开示例”即可。原来的私人问答记录保持不变。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
