"""Interactive local creation, human approval, import and publication of a snapshot."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from pydantic import ValidationError

from . import create_example_draft, publish_example
from .public_example_review import payload_digest
from .public_example_schemas import PublicExampleDraft


def write_new_json(path: Path, value: dict):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Valid JSON snapshot supplying references and corpus_id')
    parser.add_argument('--output', type=Path, required=True,
                        help='New JSON path; existing files are never overwritten')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.suffix.lower() != '.json':
        print('输出文件必须以 .json 结尾。')
        return 1
    reserved = [output, output.with_suffix('.review.json'), output.with_suffix('.import.json')]
    if any(path.exists() for path in reserved):
        print('目标或回执已存在，已停止，未覆盖旧文件。请核查现有记录。')
        return 1
    try:
        source = json.loads(args.source.read_text(encoding='utf-8-sig'))
        references = source['references']
        corpus_id = source['corpus_id']
    except (OSError, ValueError, KeyError, TypeError):
        print('依据源文件无法读取或格式错误。请指定有效的公开快照 JSON。')
        return 1

    try:
        print('依据来源：', args.source)
        print('只能填写这些依据能够支持的答案；本工具不会自动核实事实或生成答案。')
        question = input('问题：').strip()
        print('请输入答案（可多行，引用使用 [1] 等编号）；单独输入 END 结束：')
        lines = []
        while True:
            line = input()
            if line == 'END':
                break
            lines.append(line)
        payload = PublicExampleDraft.model_validate({
            'question': question, 'answer': '\n'.join(lines),
            'references': references, 'corpus_id': corpus_id,
        }).model_dump(mode='json')
        print('\n===== 待公开的完整快照 =====')
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        output.parent.mkdir(parents=True, exist_ok=True)
        write_new_json(output, payload)
        print('\n本地草稿已保存：', output)
        print('请核对：答案与引用相符、条件完整、不含私人信息，来源与许可证已保留。')
        confirmation = input('审核通过并立即公开请输入 PUBLISH；其他输入仅保存本地草稿：')
        if confirmation != 'PUBLISH':
            print('未发布，未访问数据库；保留本地草稿。')
            return 0
        write_new_json(output.with_suffix('.review.json'), {
            'review_status': 'approved',
            'review_basis': 'maintainer explicitly entered PUBLISH after full snapshot preview',
            'approved_at_utc': datetime.now(timezone.utc).isoformat(),
            'payload_sha256': payload_digest(payload),
        })
    except ValidationError as error:
        print('内容校验失败，未导入或发布：')
        for item in error.errors(include_input=False, include_url=False):
            print(' / '.join(map(str, item['loc'])) or 'snapshot', item['msg'])
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\n操作已取消，未导入或发布。已有本地文件会保留。')
        return 1
    except OSError:
        print('本地文件写入失败，未导入或发布；已有文件保留，请检查。')
        return 1

    # Reuse the existing receipt, digest and transactional publication checks.
    if create_example_draft.main(['--file', str(output), '--submit']) != 0:
        print('导入未确认，已停止。保留回执，不要自动重试。')
        return 1
    if publish_example.main(['--file', str(output), '--publish']) != 0:
        print('发布未确认。请使用 app.publish_example --file 对该文件预览核查，不要重新导入。')
        return 1
    print('公开示例已发布。刷新主页的“公开示例”即可查看，无需重启服务。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
