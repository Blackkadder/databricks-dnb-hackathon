import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { AlertCircle, ArrowLeft, Building2, CheckCircle2, Clock3, MessageSquare, Plus, Search, ShieldCheck, User, X } from 'lucide-react';
import { WorkspaceStats } from './WorkspaceStats';

type Status = 'Open' | 'In Progress' | 'Blocked' | 'Resolved' | 'Closed';
type Priority = 'Low' | 'Medium' | 'High' | 'Critical';
type Issue = {
  id: number; title: string; description: string; status: Status; priority: Priority; category: string;
  company: string; workspace_id: string; reporter_email: string; reporter_name: string;
  assignee_email: string | null; created_at: string; updated_at: string; comment_count?: number;
  comments?: Comment[]; activity?: Activity[];
};
type Comment = { id: number; author_name: string; author_email: string; body: string; created_at: string };
type Activity = { id: number; actor_email: string; action: string; detail: string; created_at: string };
type Me = { email: string; name: string; workspaceId: string };

const statuses: Status[] = ['Open', 'In Progress', 'Blocked', 'Resolved', 'Closed'];
const priorities: Priority[] = ['Low', 'Medium', 'High', 'Critical'];
const categories = ['Workspace access', 'Lakebase', 'Databricks App', 'Data', 'Authentication', 'Other'];

async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}

function Badge({ children, kind }: { children: React.ReactNode; kind: string }) {
  return <span className={`badge ${kind.toLowerCase().replace(/ /g, '-')}`}>{children}</span>;
}

function App() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [me, setMe] = useState<Me>({ email: '', name: '', workspaceId: '' });
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Issue | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const query = new URLSearchParams({ ...(status && { status }), ...(search && { search }) });
      setIssues(await json<Issue[]>(`/api/issues?${query}`));
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, [status, search]);

  useEffect(() => { json<Me>('/api/me').then(setMe).catch((e) => setError(e.message)); }, []);
  useEffect(() => { const timer = setTimeout(load, 200); return () => clearTimeout(timer); }, [load]);

  const counts = useMemo(() => Object.fromEntries(statuses.map((s) => [s, issues.filter((i) => i.status === s).length])), [issues]);

  async function openIssue(issue: Issue) {
    try { setSelected(await json<Issue>(`/api/issues/${issue.id}`)); }
    catch (e) { setError((e as Error).message); }
  }

  async function updateIssue(patch: Partial<Issue>) {
    if (!selected) return;
    try {
      await json(`/api/issues/${selected.id}`, { method: 'PATCH', body: JSON.stringify(patch) });
      await openIssue(selected); await load();
    } catch (e) { setError((e as Error).message); }
  }

  return <div className="shell">
    <header>
      <div className="brand"><div className="brand-mark">H</div><div><strong>Hackathon Help Desk</strong><span>Issue tracking & participant support</span></div></div>
      <div className="user"><div><strong>{me.name || 'Participant'}</strong><span>{me.email}</span></div><div className="avatar"><User size={17} /></div></div>
    </header>
    <main>
      {selected ? <IssueDetail issue={selected} onBack={() => setSelected(null)} onUpdate={updateIssue} onReload={() => openIssue(selected)} /> : <>
        <section className="hero">
          <div><p className="eyebrow"><ShieldCheck size={15} /> Hackathon support center</p><h1>What can we help fix?</h1><p>Report technical issues, track progress, and collaborate with the support team.</p></div>
          <button className="primary" onClick={() => setShowCreate(true)}><Plus size={18} /> Report an issue</button>
        </section>
        <WorkspaceStats />
        <section className="metrics">
          <Metric icon={<AlertCircle />} label="Needs attention" value={(counts.Open || 0) + (counts.Blocked || 0)} tone="orange" />
          <Metric icon={<Clock3 />} label="In progress" value={counts['In Progress'] || 0} tone="blue" />
          <Metric icon={<CheckCircle2 />} label="Resolved" value={(counts.Resolved || 0) + (counts.Closed || 0)} tone="green" />
          <Metric icon={<MessageSquare />} label="Total issues" value={issues.length} tone="purple" />
        </section>
        <section className="board">
          <div className="board-head"><div><h2>Issues</h2><p>{issues.length} tickets in this view</p></div><div className="filters"><label className="search"><Search size={17} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search issues, company, workspace…" /></label><select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{statuses.map((s) => <option key={s}>{s}</option>)}</select></div></div>
          {error && <div className="error">{error}</div>}
          <div className="table-wrap"><table><thead><tr><th>Issue</th><th>Company / workspace</th><th>Status</th><th>Priority</th><th>Updated</th></tr></thead><tbody>
            {!loading && issues.map((issue) => <tr key={issue.id} onClick={() => openIssue(issue)}><td><strong className="ticket">HACK-{String(issue.id).padStart(4, '0')}</strong><span className="title">{issue.title}</span><small>{issue.category} · {issue.comment_count || 0} comments</small></td><td><span className="company"><Building2 size={15} /> {issue.company}</span><small>WS {issue.workspace_id}</small></td><td><Badge kind={issue.status}>{issue.status}</Badge></td><td><Badge kind={issue.priority}>{issue.priority}</Badge></td><td>{new Date(issue.updated_at).toLocaleDateString()}</td></tr>)}
            {loading && <tr><td colSpan={5} className="empty">Loading issues…</td></tr>}
            {!loading && !issues.length && <tr><td colSpan={5} className="empty">No issues match this view.</td></tr>}
          </tbody></table></div>
        </section>
      </>}
    </main>
    {showCreate && <CreateIssue me={me} onClose={() => setShowCreate(false)} onCreated={async (issue) => { setShowCreate(false); await load(); await openIssue(issue); }} />}
  </div>;
}

function Metric({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: string }) {
  return <div className="metric"><div className={`metric-icon ${tone}`}>{icon}</div><div><strong>{value}</strong><span>{label}</span></div></div>;
}

function CreateIssue({ me, onClose, onCreated }: { me: Me; onClose: () => void; onCreated: (issue: Issue) => void }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try { onCreated(await json<Issue>('/api/issues', { method: 'POST', body: JSON.stringify(data) })); }
    catch (e) { setError((e as Error).message); setBusy(false); }
  }
  return <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><form className="dialog" onSubmit={submit}><div className="dialog-head"><div><h2>Report an issue</h2><p>Give the support team enough detail to reproduce the problem.</p></div><button type="button" className="icon-button" onClick={onClose}><X /></button></div>
    <div className="form-grid"><label className="wide">Title<input name="title" required minLength={3} placeholder="Briefly describe the problem" /></label><label className="wide">Description<textarea name="description" required minLength={10} rows={5} placeholder="What happened, what did you expect, and what have you tried?" /></label><label>Company<input name="company" required placeholder="Company name" /></label><label>Workspace ID<input value={me.workspaceId || '7474651394607811'} readOnly aria-readonly="true" /></label><label>Priority<select name="priority" defaultValue="Medium">{priorities.map((p) => <option key={p}>{p}</option>)}</select></label><label>Category<select name="category" defaultValue="Other">{categories.map((c) => <option key={c}>{c}</option>)}</select></label><label className="wide">Assignee email <span>(optional)</span><input type="email" name="assigneeEmail" placeholder="support@databricks.com" /></label></div>
    {error && <div className="error">{error}</div>}<div className="dialog-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Submitting…' : 'Submit issue'}</button></div></form></div>;
}

function IssueDetail({ issue, onBack, onUpdate, onReload }: { issue: Issue; onBack: () => void; onUpdate: (patch: Partial<Issue>) => void; onReload: () => void }) {
  const [comment, setComment] = useState(''); const [error, setError] = useState('');
  async function addComment(event: FormEvent) { event.preventDefault(); try { await json(`/api/issues/${issue.id}/comments`, { method: 'POST', body: JSON.stringify({ body: comment }) }); setComment(''); onReload(); } catch (e) { setError((e as Error).message); } }
  return <div className="detail"><button className="back" onClick={onBack}><ArrowLeft size={17} /> Back to issues</button><div className="detail-grid"><section className="issue-main"><div className="issue-heading"><span>HACK-{String(issue.id).padStart(4, '0')}</span><h1>{issue.title}</h1><div><Badge kind={issue.status}>{issue.status}</Badge><Badge kind={issue.priority}>{issue.priority}</Badge><Badge kind="neutral">{issue.category}</Badge></div></div><div className="description"><h3>Description</h3><p>{issue.description}</p></div><div className="comments"><h3>Conversation <span>{issue.comments?.length || 0}</span></h3>{issue.comments?.map((c) => <article key={c.id}><div className="avatar small">{c.author_name[0]?.toUpperCase()}</div><div><strong>{c.author_name}</strong><time>{new Date(c.created_at).toLocaleString()}</time><p>{c.body}</p></div></article>)}<form onSubmit={addComment}><textarea value={comment} onChange={(e) => setComment(e.target.value)} required placeholder="Add a comment…" rows={3} />{error && <div className="error">{error}</div>}<button className="primary">Add comment</button></form></div></section><aside><div className="side-card"><h3>Ticket details</h3><label>Status<select value={issue.status} onChange={(e) => onUpdate({ status: e.target.value as Status })}>{statuses.map((s) => <option key={s}>{s}</option>)}</select></label><label>Priority<select value={issue.priority} onChange={(e) => onUpdate({ priority: e.target.value as Priority })}>{priorities.map((p) => <option key={p}>{p}</option>)}</select></label><Info label="Company" value={issue.company} /><Info label="Workspace ID" value={issue.workspace_id} /><Info label="Reporter" value={issue.reporter_email} /><Info label="Assignee" value={issue.assignee_email || 'Unassigned'} /><Info label="Created" value={new Date(issue.created_at).toLocaleString()} /></div><div className="side-card activity"><h3>Activity</h3>{issue.activity?.map((a) => <div key={a.id}><i /><p><strong>{a.actor_email}</strong> {a.action}<span>{a.detail}</span><time>{new Date(a.created_at).toLocaleString()}</time></p></div>)}</div></aside></div></div>;
}

function Info({ label, value }: { label: string; value: string }) { return <div className="info"><span>{label}</span><strong>{value}</strong></div>; }
export default App;
