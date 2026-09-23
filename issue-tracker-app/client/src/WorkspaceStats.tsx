import { useCallback, useEffect, useState } from 'react';
import { AppWindow, Boxes, Database, RefreshCw, Table2, UsersRound, Waypoints, Workflow } from 'lucide-react';

type MetricState = {
  value: number | null;
  status: 'available' | 'unavailable';
  error?: string;
};

type WorkspaceStatsResponse = {
  stats: Record<MetricKey, MetricState>;
  calculatedAt: string;
};

type MetricKey = 'groups' | 'schemas' | 'tables' | 'apps' | 'lakebaseInstances' | 'lakeflowJobs' | 'lakeflowPipelines';

const metrics: Array<{ key: MetricKey; label: string; icon: typeof UsersRound; tone: string }> = [
  { key: 'groups', label: 'Groups', icon: UsersRound, tone: 'teal' },
  { key: 'schemas', label: 'Schemas', icon: Boxes, tone: 'blue' },
  { key: 'tables', label: 'Tables', icon: Table2, tone: 'green' },
  { key: 'apps', label: 'Apps', icon: AppWindow, tone: 'orange' },
  { key: 'lakebaseInstances', label: 'Lakebase instances', icon: Database, tone: 'purple' },
  { key: 'lakeflowJobs', label: 'Lakeflow jobs', icon: Workflow, tone: 'blue' },
  { key: 'lakeflowPipelines', label: 'Lakeflow pipelines', icon: Waypoints, tone: 'teal' },
];

export function WorkspaceStats() {
  const [data, setData] = useState<WorkspaceStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`/api/workspace-stats${refresh ? '?refresh=true' : ''}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'Workspace statistics could not be loaded');
      setData(body);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Workspace statistics could not be loaded');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const calculated = data?.calculatedAt
    ? new Date(data.calculatedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : null;

  return <section className="workspace-stats" aria-labelledby="workspace-stats-heading" aria-busy={loading}>
    <div className="workspace-stats-head">
      <div>
        <p className="workspace-stats-kicker">Workspace overview</p>
        <h2 id="workspace-stats-heading">Workspace resources</h2>
        <p>{calculated ? `Calculated at ${calculated}` : 'Live counts from Databricks and Unity Catalog'}</p>
      </div>
      <button className="stats-refresh" type="button" onClick={() => void load(true)} disabled={loading} aria-label="Refresh workspace statistics">
        <RefreshCw size={16} className={loading ? 'spin' : ''} aria-hidden="true" />
        <span>{loading ? 'Refreshing' : 'Refresh'}</span>
      </button>
    </div>
    {error && <div className="workspace-stats-error"><Database size={18} /> <span>{error}</span></div>}
    <div className="workspace-stats-grid">
      {metrics.map(({ key, label, icon: Icon, tone }) => {
        const metric = data?.stats?.[key];
        const unavailable = metric?.status === 'unavailable';
        return <article className="workspace-stat" key={key} title={unavailable ? metric.error : undefined}>
          <div className={`workspace-stat-icon ${tone}`}><Icon size={19} aria-hidden="true" /></div>
          <div>
            <strong className={unavailable ? 'unavailable' : ''}>
              {loading && !data ? <span className="stat-skeleton" /> : unavailable || !metric ? '—' : metric.value?.toLocaleString() ?? '—'}
            </strong>
            <span>{label}</span>
            {unavailable && <small>Unavailable</small>}
          </div>
        </article>;
      })}
    </div>
  </section>;
}
