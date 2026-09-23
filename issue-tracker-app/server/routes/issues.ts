import type { Application, Request } from 'express';
import { z } from 'zod';

const STATUSES = ['Open', 'In Progress', 'Blocked', 'Resolved', 'Closed'] as const;
const PRIORITIES = ['Low', 'Medium', 'High', 'Critical'] as const;
const CATEGORIES = ['Workspace access', 'Lakebase', 'Databricks App', 'Data', 'Authentication', 'Other'] as const;
const WORKSPACE_IDS_BY_HOST: Record<string, string> = {
  'dbc-9d25a17d-f58c.cloud.databricks.com': '7474651394607811',
  'dbc-7f5ee9e8-6a84.cloud.databricks.com': '7474650842988229',
};

function workspaceId() {
  if (process.env.WORKSPACE_ID) return process.env.WORKSPACE_ID;
  const host = (process.env.DATABRICKS_HOST || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
  return WORKSPACE_IDS_BY_HOST[host] || '7474651394607811';
}

interface Queryable {
  query(text: string, params?: unknown[]): Promise<{ rows: Record<string, any>[]; rowCount?: number | null }>;
}

interface AppKitWithLakebase {
  lakebase: Queryable;
  server: { extend(fn: (app: Application) => void): void };
}

const createIssueSchema = z.object({
  title: z.string().trim().min(3).max(160),
  description: z.string().trim().min(10).max(10000),
  company: z.string().trim().min(2).max(160),
  priority: z.enum(PRIORITIES).default('Medium'),
  category: z.enum(CATEGORIES).default('Other'),
  assigneeEmail: z.string().email().optional().or(z.literal('')),
});

const updateIssueSchema = z.object({
  status: z.enum(STATUSES).optional(),
  priority: z.enum(PRIORITIES).optional(),
  assigneeEmail: z.string().email().nullable().optional().or(z.literal('')),
  title: z.string().trim().min(3).max(160).optional(),
  description: z.string().trim().min(10).max(10000).optional(),
});

const commentSchema = z.object({ body: z.string().trim().min(1).max(5000) });
function identity(req: Request) {
  // Databricks Apps injects this trusted header after authenticating the user.
  // Database access stays on the app service principal; this identity is stored
  // on every user-authored record for attribution and audit history.
  const email = req.header('x-forwarded-email');
  if (!email && process.env.NODE_ENV === 'production') throw new Error('Authenticated user identity is missing');
  const resolvedEmail = email || process.env.USER || 'local-user@databricks.com';
  return {
    email: resolvedEmail,
    name: req.header('x-forwarded-preferred-username') || resolvedEmail.split('@')[0],
  };
}

const SETUP_SQL = `
  CREATE SCHEMA IF NOT EXISTS issue_tracker;
  CREATE TABLE IF NOT EXISTS issue_tracker.issues (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','In Progress','Blocked','Resolved','Closed')),
    priority TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Low','Medium','High','Critical')),
    category TEXT NOT NULL DEFAULT 'Other',
    company TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    reporter_email TEXT NOT NULL,
    reporter_name TEXT NOT NULL,
    assignee_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE TABLE IF NOT EXISTS issue_tracker.comments (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES issue_tracker.issues(id) ON DELETE CASCADE,
    author_email TEXT NOT NULL,
    author_name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE TABLE IF NOT EXISTS issue_tracker.activity (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT NOT NULL REFERENCES issue_tracker.issues(id) ON DELETE CASCADE,
    actor_email TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
`;

const SEED_SQL = `
  INSERT INTO issue_tracker.issues
    (title, description, status, priority, category, company, workspace_id, reporter_email, reporter_name, assignee_email)
  SELECT * FROM (VALUES
    ('Cannot connect to Lakebase branch', 'Connection attempts time out after the workspace was assigned.', 'Open', 'Critical', 'Lakebase', 'Acme Analytics', $1, 'alex@acme.example', 'Alex Morgan', NULL),
    ('App deployment is stuck', 'The deployment has remained in the starting state for more than fifteen minutes.', 'In Progress', 'High', 'Databricks App', 'Northstar Labs', $1, 'priya@northstar.example', 'Priya Shah', 'rob.bajra@databricks.com'),
    ('Need sample data access', 'Our team can open the workspace but cannot see the hackathon sample catalog.', 'Resolved', 'Medium', 'Data', 'Bright River', $1, 'sam@brightriver.example', 'Sam Lee', NULL)
  ) AS seed(title, description, status, priority, category, company, workspace_id, reporter_email, reporter_name, assignee_email)
  WHERE NOT EXISTS (SELECT 1 FROM issue_tracker.issues);
`;

export async function setupIssueRoutes(appkit: AppKitWithLakebase) {
  await appkit.lakebase.query(SETUP_SQL);
  await appkit.lakebase.query(SEED_SQL, [workspaceId()]);

  appkit.server.extend((app) => {
    app.get('/api/me', async (req, res) => {
      try {
        const user = identity(req);
        res.json({ ...user, workspaceId: workspaceId() });
      } catch (error) {
        res.status(401).json({ error: (error as Error).message });
      }
    });

    app.get('/api/issues', async (req, res) => {
      try {
        identity(req);
        const query = appkit.lakebase;
        const status = typeof req.query.status === 'string' ? req.query.status : '';
        const search = typeof req.query.search === 'string' ? req.query.search.trim() : '';
        const result = await query.query(
          `SELECT i.*,
             (SELECT COUNT(*)::int FROM issue_tracker.comments c WHERE c.issue_id = i.id) AS comment_count
           FROM issue_tracker.issues i
           WHERE ($1 = '' OR i.status = $1)
             AND ($2 = '' OR i.title ILIKE '%' || $2 || '%' OR i.company ILIKE '%' || $2 || '%' OR i.workspace_id ILIKE '%' || $2 || '%')
           ORDER BY CASE i.priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, i.updated_at DESC`,
          [status, search],
        );
        res.json(result.rows);
      } catch (error) {
        console.error('Failed to list issues', error);
        res.status(500).json({ error: 'Failed to list issues' });
      }
    });

    app.get('/api/issues/:id', async (req, res) => {
      try {
        identity(req);
        const query = appkit.lakebase;
        const issue = await query.query('SELECT * FROM issue_tracker.issues WHERE id = $1', [req.params.id]);
        if (!issue.rows[0]) return void res.status(404).json({ error: 'Issue not found' });
        const comments = await query.query('SELECT * FROM issue_tracker.comments WHERE issue_id = $1 ORDER BY created_at', [req.params.id]);
        const activity = await query.query('SELECT * FROM issue_tracker.activity WHERE issue_id = $1 ORDER BY created_at DESC', [req.params.id]);
        res.json({ ...issue.rows[0], comments: comments.rows, activity: activity.rows });
      } catch (error) {
        console.error('Failed to load issue', error);
        res.status(500).json({ error: 'Failed to load issue' });
      }
    });

    app.post('/api/issues', async (req, res) => {
      try {
        const body = createIssueSchema.parse(req.body);
        const user = identity(req);
        const query = appkit.lakebase;
        const result = await query.query(
          `WITH new_issue AS (
             INSERT INTO issue_tracker.issues
               (title, description, priority, category, company, workspace_id, reporter_email, reporter_name, assignee_email)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
             RETURNING *
           ), log_activity AS (
             INSERT INTO issue_tracker.activity (issue_id, actor_email, action, detail)
             SELECT id, $7, 'created', 'Issue reported' FROM new_issue
           )
           SELECT * FROM new_issue`,
          [body.title, body.description, body.priority, body.category, body.company, workspaceId(), user.email, user.name, body.assigneeEmail || null],
        );
        const issue = result.rows[0];
        res.status(201).json(issue);
      } catch (error) {
        if (error instanceof z.ZodError) return void res.status(400).json({ error: error.issues[0]?.message });
        console.error('Failed to create issue', error);
        res.status(500).json({ error: 'Failed to create issue' });
      }
    });

    app.patch('/api/issues/:id', async (req, res) => {
      try {
        const body = updateIssueSchema.parse(req.body);
        const user = identity(req);
        const query = appkit.lakebase;
        const current = await query.query('SELECT * FROM issue_tracker.issues WHERE id = $1', [req.params.id]);
        if (!current.rows[0]) return void res.status(404).json({ error: 'Issue not found' });
        const before = current.rows[0];
        const result = await query.query(
          `UPDATE issue_tracker.issues SET
             status = COALESCE($2, status), priority = COALESCE($3, priority),
             assignee_email = CASE WHEN $4::boolean THEN $5 ELSE assignee_email END,
             title = COALESCE($6, title), description = COALESCE($7, description), updated_at = NOW()
           WHERE id = $1 RETURNING *`,
          [req.params.id, body.status, body.priority, Object.prototype.hasOwnProperty.call(body, 'assigneeEmail'), body.assigneeEmail || null, body.title, body.description],
        );
        const changed = Object.keys(body).map((key) => `${key}: ${String(before[key.replace(/[A-Z]/g, (m) => `_${m.toLowerCase()}`)])} → ${String((body as any)[key] || 'Unassigned')}`).join('; ');
        await query.query(`INSERT INTO issue_tracker.activity (issue_id, actor_email, action, detail) VALUES ($1,$2,'updated',$3)`, [req.params.id, user.email, changed]);
        res.json(result.rows[0]);
      } catch (error) {
        if (error instanceof z.ZodError) return void res.status(400).json({ error: error.issues[0]?.message });
        console.error('Failed to update issue', error);
        res.status(500).json({ error: 'Failed to update issue' });
      }
    });

    app.post('/api/issues/:id/comments', async (req, res) => {
      try {
        const { body } = commentSchema.parse(req.body);
        const user = identity(req);
        const query = appkit.lakebase;
        const result = await query.query(
          `INSERT INTO issue_tracker.comments (issue_id, author_email, author_name, body)
           VALUES ($1,$2,$3,$4) RETURNING *`, [req.params.id, user.email, user.name, body],
        );
        await query.query(`INSERT INTO issue_tracker.activity (issue_id, actor_email, action, detail) VALUES ($1,$2,'commented','Added a comment')`, [req.params.id, user.email]);
        await query.query('UPDATE issue_tracker.issues SET updated_at = NOW() WHERE id = $1', [req.params.id]);
        res.status(201).json(result.rows[0]);
      } catch (error) {
        if (error instanceof z.ZodError) return void res.status(400).json({ error: error.issues[0]?.message });
        console.error('Failed to add comment', error);
        res.status(500).json({ error: 'Failed to add comment' });
      }
    });
  });
}
