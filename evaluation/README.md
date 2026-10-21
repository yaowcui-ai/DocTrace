# 评测与可核查证据

知识库固定为 GitLab HR v3：68 份文档、318 个片段，1200 token / overlap 100，1024 维向量。对每道题使用同一实际捕获候选、相同图上下文、相同文本 token 余量和最多 20 个片段。mix 总预算为 40,000 token，不全部用于文档。

| 集合 | 原排序：证据组 / 完整题 | 整句前置重排 | 最终策略 |
| --- | --- | --- | --- |
| 开发集：20 题、45 组 | 39/45；15/20 | 43/45；18/20 | **44/45；19/20** |
| 内部保留题：12 题、26 组 | 17/26；7/12 | 26/26；12/12 | **26/26；12/12** |

最终策略为整句重排加条件性子问题融合。子问题仅对明确复合句式生效，不按题号、答案或目标文件挑片段。无重排分数门槛；不同子问题分数不直接相加。

## 如何核查

- [开发集逐题结果](diagnostics/hr_medium_policy_dev_verified_20261016.json)
- [内部保留题逐题结果](diagnostics/hr_medium_policy_holdout_verified_20261016.json)
- [策略冻结](freezes/hr_medium_policy_v1.json)
- [内部保留题冻结](freezes/hr_medium_holdout_v1.json)
- [开发题与标注](hr_medium_dev_v2.json)
- [内部保留题与标注](hr_medium_holdout_v1.json)
- [原始证据压缩文件及解压后 SHA-256](artifacts/manifest.json)

原始报告以 `.json.gz` 保存，解压后字节和 SHA-256 与本地历史原件一致；未重新调用模型，也未用新结果覆盖旧报告。它们包含真实候选、排序、预算和策略输出。部分报告中的旧相对路径指向当时运行目录；仓库公开的是选定证据，不包含整套私人运行目录和缓存。

解压某份报告并核验：

```python
from pathlib import Path
import gzip, hashlib, json
root = Path('evaluation/artifacts')
for item in json.loads((root / 'manifest.json').read_text()):
    data = gzip.decompress(Path(item['file']).read_bytes())
    assert hashlib.sha256(data).hexdigest() == item['uncompressed_sha256']
    print(Path(item['file']).name, len(data), 'verified')
```

## 失败怎样推动修改

- **M03：**向量与实体召回已找到必要证据，但合并后的数量/token 选择丢掉了它。因此把重排前移到截断之前，而不是单纯增加一个截断后的重排步骤。
- **M17：**整句重排仍漏掉复合问题中的导师书面目标条件。明确子问题的排序融合补齐该题，使开发覆盖由 43/45 达到 44/45。
- **M19：**原排序 3/3，最终策略 2/3；必要股权批准证据降位，分支也未补回。这个退化保留在逐题结果中，没有改金标准或硬塞目标文件。

## 指标限制

证据组覆盖检查标注原文或冻结的合法替代是否出现在最终片段中。它不是最终答案准确率，也不证明引用解释正确。题目是基于同一知识库编制的小样本内部题集，并非外部独立盲测，部分证据组共享片段或政策。

保留题上整句重排已达到 26/26，子问题没有额外覆盖收益；只能确认其在开发题 M17 上的作用。当前证据不支持宣称提高所有问题效果、降低 token 成本或加速请求。页面展示的 naive / mix 对照预算和候选不同，不替代这里的固定同候选实验。
