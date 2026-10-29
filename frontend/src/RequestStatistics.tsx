import {useEffect, useState} from 'react';
import './RequestStatistics.css';

type Stats = {sample_size: number; sample_limit: number; synthetic_excluded: number;
  completed: number; failed: number; processing: number;
  recorded_latency_ms: {p50: number | null; p95: number | null}};
type FetchApi = <T>(path: string, method?: string, body?: unknown, key?: string) => Promise<T>;

export function RequestStatistics({api}: {api: FetchApi}) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let current = true;
    setError(''); setStats(null);
    void api<Stats>('/api/v1/admin/stats').then(value => {if (current) setStats(value);})
      .catch(() => {if (current) setError('请求统计暂时不可用，请刷新重试。');});
    return () => {current = false;};
  }, [api, version]);
  const ms = (value: number | null) => value === null ? '未测' : `${Math.round(value)} ms`;
  return <section className="request-statistics" aria-labelledby="stats-heading">
    <div className="section-heading"><h2 id="stats-heading">请求运行统计</h2><button className="quiet-button" onClick={() => setVersion(v => v + 1)}>刷新请求统计</button></div>
    {error && <p role="alert" className="error-message">{error}</p>}
    {!stats && !error && <p role="status">正在读取聚合统计…</p>}
    {stats && <><dl className="stats-row">
      <div><dt>已完成</dt><dd>{stats.completed}</dd></div>
      <div><dt>失败</dt><dd>{stats.failed}</dd></div>
      <div><dt>处理中</dt><dd>{stats.processing}</dd></div>
      <div><dt>记录耗时 P50 / P95</dt><dd>{ms(stats.recorded_latency_ms.p50)} / {ms(stats.recorded_latency_ms.p95)}</dd></div>
    </dl><p className="muted">最近 {stats.sample_limit} 条记录内统计 {stats.sample_size} 条，已排除 {stats.synthetic_excluded} 条合成压测记录。完成状态不代表答案已经事实核验。</p></>}
  </section>;
}
