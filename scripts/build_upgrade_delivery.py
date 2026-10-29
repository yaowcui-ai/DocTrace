"""Summarize actual saved evidence without model calls or rewriting raw attempts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def main():
    from app.benchmark import latency_summary
    run = 'evaluation/upgrade/new_retrieval/20261028T074830Z_2d0d3d18'
    assembled = read(run+'/assembled_20261029T005711Z_136e89.json')
    retrieval = read('evaluation/upgrade/reports/retrieval_internal_109.json')
    generation = read('evaluation/upgrade/generation/20261028T123140Z_53477acb/source_review.json')
    performance = read('evaluation/upgrade/performance/20261028T072036Z_44502f68/report.json')
    dataset = read('evaluation/upgrade_dataset/internal-test-v1/dataset.json')
    cases = {case['id']: case for case in dataset['cases']}
    by_id = {row['case_id']: row for row in assembled['records']}
    metrics = {}
    for variant in ('B0', 'B1', 'B2', 'B3'):
        selected = [row['variants'][variant] for row in retrieval['records']]
        def mean(field, key):
            values = [row[field][key] for row in selected if row[field][key] is not None]
            return round(sum(values)/len(values), 6) if values else None
        metrics[variant] = {**retrieval['summary'][variant],
            'macro_recall_at_5': mean('recall_at_5', 'recall'),
            'macro_recall_at_10': mean('recall_at_10', 'recall'),
            'macro_mrr_at_10': mean('recall_at_10', 'mrr'),
            'strict_gold_ndcg_at_10_proxy': mean('strict_gold_proxy_at_10', 'ndcg'),
            'strict_non_gold_fraction_at_10_proxy': mean('strict_gold_proxy_at_10', 'non_gold_fraction'),
            'semantic_ndcg_at_10': None, 'semantic_irrelevant_ratio': None}
    categories = {}
    for row in retrieval['records']:
        kind = cases[row['case_id']]['question_type']
        item = categories.setdefault(kind, {'cases': 0, 'B0_complete': 0, 'B3_complete': 0})
        item['cases'] += 1
        for variant in ('B0', 'B3'):
            value = row['variants'][variant]
            item[variant+'_complete'] += value['matched_groups'] == value['expected_groups']
    recovered = [row for row in assembled['all_attempts'] if '/retries/' in row['path']]
    evidence = {'created_at': datetime.now(timezone.utc).isoformat(),
        'dataset_id': dataset['dataset_id'], 'dataset_sha256': assembled['dataset_sha256'],
        'requested_cases': 112, 'scorable_cases': 109, 'unresolved_cases': assembled['failures'],
        'metrics': metrics, 'by_question_type': categories,
        'original_attempt_count': 112, 'explicit_capture_recovery_attempts': len(recovered),
        'successful_capture_recoveries': sum(row['status'] == 'completed' for row in recovered),
        'B1_B2_identical_cases': sum(row['B1_equals_B2_ids'] for row in retrieval['records']),
        'B2_B3_identical_cases': sum(row['variants']['B2']['selected_ids'] == row['variants']['B3']['selected_ids'] for row in retrieval['records']),
        'measured_original_retrieval_seconds': latency_summary([row['retrieval_seconds'] for row in assembled['records'] if row.get('retrieval_seconds') is not None]),
        'whole_rerank_seconds_successful_attempts': latency_summary([row['policy']['whole']['elapsed_seconds'] for row in assembled['records'] if 'elapsed_seconds' in row['policy']['whole']]),
        'selector_execution': retrieval['selector_execution'],
        'limits': ['109/112 scorable subset; unresolved failures are not treated as correct or silently dropped.',
            'Same saved complete candidate pool and supplier scores; these are selector ablations, not four independent production requests.',
            'Exact-source gold covers required evidence, not exhaustive semantic relevance.',
            'Token totals are rendered chunk tokens; they exclude graph and generation output.',
            'Provider aliases are mutable. Recorded latency includes cache effects and explicit retries; not a controlled cold comparison.',
            'Source/output review is automated-assisted, not an external human blind trial.']}
    reports = ROOT/'evaluation/upgrade/reports'
    def save(name, body):
        target = reports/name
        with target.open('x', encoding='utf-8') as stream:
            json.dump(body, stream, ensure_ascii=False, indent=2)
    save('retrieval_internal.json', evidence)
    save('generation.json', generation)
    save('performance.json', {key: value for key, value in performance.items() if key != 'levels'} | {
        'levels': [{key: value for key, value in level.items() if key != 'records'} for level in performance['levels']]})
    save('baseline.json', {'historical_development_cases': 20, 'historical_evidence_groups': 45,
        'B0': '39/45 groups, 15/20 complete', 'B1_native_equals_B2': '43/45 groups, 18/20 complete',
        'B3': '44/45 groups, 19/20 complete', 'new_experiment': False,
        'pinned_image_revision': '28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c',
        'upstream_reranks_before_topk': True, 'original_files_preserved': True})
    table = '\n'.join(f"| {name} | {m['macro_recall_at_5']:.4f} | {m['macro_recall_at_10']:.4f} | {m['macro_mrr_at_10']:.4f} | {m['matched_groups']}/{m['expected_groups']} | {m['complete_cases']}/109 | {m['tokens']:,} |" for name, m in metrics.items())
    category_table = '\n'.join(f"| {kind} | {value['cases']} | {value['B0_complete']} | {value['B3_complete']} |" for kind, value in categories.items())
    text = f'''# 升级实验实际结果

截至2026年10月29日（北京时间）。这是内部公开政策快照实验；没有真实企业用户测试或外部人工盲测。原始结果、失败和恢复尝试均保留，不把旧开发题重新包装为新测试。

## 历史基线与版本核查

原20题/45组：B0关闭重排39/45；B1原生重排与B2自定义整句重排均43/45；B3条件性融合44/45。历史M19退化保留。固定镜像 revision `28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c`；其原生utils已经先重排、再top-k/token截断。不能声称该排序位置是自创，也不能宣称B2优于原生重排。

来源：`evaluation/upgrade/reports/retrieval.json`、`docs/UPGRADE_AUDIT.md`、`evaluation/upgrade/20261028T023825Z_audit_06809179/operate.patch`。

## 新内部测试：112题，109题可评分

113道来源草稿经逐条原文哈希/引文/片段校验，收紧9处参考答案；排除已在安全烟测观察过的U025，冻结112题/127组。冻结7个策略文件及数据哈希后才检索。旧开发20题和内部验证12题继续保留；新测试不用于本轮调参。后续若按本结果改策略，必须转为回归集。

112次原始尝试；36次明确的捕获候选重排恢复中34次成功、2次超时。恢复只重用候选，不重复Embedding/图检索。首批出现429却未立即停止是执行缺陷，已补调用预算、节流和429熔断，原失败未覆盖。U090、U109恢复仍超时；U091在Docker中断时停留在提交未确认，均不计成功。最终109题/124组可评分，结果有成功子集偏倚，不能宣传成112题全通过。

同题共享完整合并池、图预算、40000总token、20块上限和同次重排分数；不混入金标准，不补召回池外证据。

| 方案 | Recall@5 | Recall@10 | MRR@10 | 证据组覆盖 | 整题完整 | 原文块token合计 |
|---|---:|---:|---:|---:|---:|---:|
{table}

Recall/MRR按题宏平均、分母为已标注正例；覆盖为微观证据组统计。token只计原文块，不含图描述及输出。B1/B2在109/109题同序；B3在本次也与B2相同，未观察到融合额外收益。不能用旧20题收益替代新测试结论。

| 问题类型 | 可评题 | B0完整 | B3完整 |
|---|---:|---:|---:|
{category_table}

所有片段未做穷尽相关性标注，因此语义nDCG@10及无关比例为null。机器报告另列严格金标准代理nDCG/非金标准比例，不能把它们称为真实语义噪声率。检索、重排和选择器时间分开保存；失败重试、缓存及本机负载会影响耗时，不给四方案冷延迟排名。

U034、U110在重排后仍缺标注组；检索成功不等于证据完整。B0已正确的U034在重排后退化，不能只报总体提升。逐题ID及选择结果见 `evaluation/upgrade/reports/retrieval_internal_109.json`；聚合见 `retrieval_internal.json`。

原版函数重放先在固定容器执行；Docker故障后，使用相同SHA256原始定义的本机顺序执行入口。已在61题×4方案比较，最终ID和渲染token完全一致。只替换线程调度包装，不修改排序或截断函数；该执行时间不是线上吞吐。

## 固定上下文生成：9题、18次实际请求

同模型别名、同提示词、30000字符完整块预算、输出最多800token；相同问题及上下文复用一次生成，不将B1/B2/B3相同结果当作独立重复实验。

| 方案 | 主答案完整正确 | 部分正确 | 未回答正确 |
|---|---:|---:|---:|
| B0 | 5/9 | 2/9 | 2/9 |
| B1=B2=B3 | 8/9 | 1/9 | 0/9 |

只有当时可评分子集的9题，不是112题答案准确率。U003/U004的B0因最终字符上下文缺必要政策而保守拒答，定位为证据组织问题；U005重排版有原文却把出生/收养的“或”条件扩为绝对不符合，属于生成条件范围错误。U003另有可能把PTO审批规则扩到记录更正的附加主张，保留风险。

引用编号结构9/9有效只证明编号存在，不能声称语义引用准确率100%。主结论与限定词做来源核对并保存理由；**尚未完成全句级引用精确率、完整条件逐项量化及新题全集生成**。未使用LLM裁判替代核查，也未宣称真人盲评。

## 安全、性能、业务边界

真实生成3次固定证据烟测均HTTP200、未输出攻击标记且含引用。一次只匹配“永久”的规则把“无固定期限”误报，保留原退出1并单列复核，不重试冲成通过。三次烟测不证明抗注入免疫。权限、数据库异常等另见工程报告。

并发测试为实际HTTP+MySQL、模拟0.1秒供应商：1/5/10/20每档20请求，成功20/4/5/7，高并发其余因账号准入返回429。只验证业务层与保护策略，不是实际LLM吞吐或生产SLA。8道模拟业务任务中关键词与保存RAG排序都7/8完整，未证明使用时间或满意度改善。

## 可复现与保存

运行命令和退出码在 `evaluation/upgrade/<UTC_UUID>/command.json,result.json,output.log`。原始逐题候选和模型输入输出本地保留，公开发布只白名单复制公共政策证据、脱敏结果和哈希。禁止提交.env、个人历史、Cookie、数据库备份。

```powershell
.\\.venv\\Scripts\\python.exe scripts/assemble_upgrade_batch.py --run evaluation/upgrade/new_retrieval/20261028T074830Z_2d0d3d18
.\\.venv\\Scripts\\python.exe -m app.ablation_replay --host-snapshot --source <新生成的assembled.json> --output <新的结果文件.json>
```

离线选择器需 `requirements-benchmark.txt` 及o200k_base公开词表缓存。没有原始捕获文件时，不可凭汇总逆造结果；公开报告可复核排序ID、指标与来源，但独立重新捕获仍需配置模型并承担实际调用。
'''
    (ROOT/'docs/EVALUATION_REPORT.md').write_text(text, encoding='utf-8')
    print('Evidence summaries and evaluation report created; model calls 0.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
