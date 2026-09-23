import { createWorkspaceClient } from '@databricks/appkit';
import type { Application } from 'express';

const CACHE_TTL_MS = 3 * 60 * 1000;
const REQUEST_TIMEOUT_MS = 15_000;
const HACKATHON_CATALOG = 'hackathon';
const TABLE_TYPES = new Set(['EXTERNAL', 'EXTERNAL_SHALLOW_CLONE', 'FOREIGN', 'MANAGED', 'MANAGED_SHALLOW_CLONE']);

export type WorkspaceStat =
  | { value: number; status: 'available' }
  | { value: null; status: 'unavailable'; error: string };

export interface WorkspaceStatsResponse {
  stats: {
    groups: WorkspaceStat;
    schemas: WorkspaceStat;
    tables: WorkspaceStat;
    apps: WorkspaceStat;
    lakebaseInstances: WorkspaceStat;
    lakeflowJobs: WorkspaceStat;
    lakeflowPipelines: WorkspaceStat;
  };
  calculatedAt: string;
}

interface WorkspaceStatsClient {
  catalogs: { list(request: Record<string, unknown>): AsyncIterable<{ name?: string }> };
  schemas: { list(request: Record<string, unknown>): AsyncIterable<{ name?: string }> };
  tables: { listSummaries(request: Record<string, unknown>): AsyncIterable<{ table_type?: string }> };
  apps: { list(request: Record<string, unknown>): AsyncIterable<unknown> };
  jobs: { list(request: Record<string, unknown>): AsyncIterable<unknown> };
  pipelines: { listPipelines(request: Record<string, unknown>): AsyncIterable<unknown> };
  apiClient: {
    request(options: {
      path: string;
      method: 'GET';
      query: Record<string, unknown>;
      headers: Headers;
      raw: false;
    }): Promise<unknown>;
  };
}

interface ScimListResponse<T> {
  Resources?: T[];
  totalResults?: number;
}

let cached: { expiresAt: number; response: WorkspaceStatsResponse } | undefined;
let refreshInFlight: Promise<WorkspaceStatsResponse> | undefined;

async function count<T>(items: AsyncIterable<T>, predicate: (item: T) => boolean = () => true) {
  let total = 0;
  for await (const item of items) if (predicate(item)) total += 1;
  return total;
}

async function visibleCatalogNames(client: WorkspaceStatsClient) {
  const names: string[] = [];
  for await (const catalog of client.catalogs.list({ max_results: 0, include_browse: true })) {
    if (catalog.name && catalog.name.toLowerCase() !== 'system') names.push(catalog.name);
  }
  return names;
}

async function countSchemas(client: WorkspaceStatsClient) {
  return count(
    client.schemas.list({ catalog_name: HACKATHON_CATALOG, max_results: 0, include_browse: true }),
    (schema) => schema.name?.toLowerCase() !== 'information_schema',
  );
}

async function countTables(client: WorkspaceStatsClient) {
  let total = 0;
  for (const catalogName of await visibleCatalogNames(client)) {
    total += await count(
      client.tables.listSummaries({ catalog_name: catalogName, max_results: 0 }),
      (table) => Boolean(table.table_type && TABLE_TYPES.has(table.table_type)),
    );
  }
  return total;
}

async function countLakebaseProjects(client: WorkspaceStatsClient) {
  let total = 0;
  let pageToken: string | undefined;
  do {
    const response = await client.apiClient.request({
      path: '/api/2.0/postgres/projects',
      method: 'GET',
      query: { page_size: 100, page_token: pageToken, show_deleted: false },
      headers: new Headers(),
      raw: false,
    }) as { projects?: unknown[]; next_page_token?: string };
    total += response.projects?.length ?? 0;
    pageToken = response.next_page_token;
  } while (pageToken);
  return total;
}

async function countScimResources<T>(
  client: WorkspaceStatsClient,
  path: string,
  attributes: string,
  predicate: (item: T) => boolean = () => true,
) {
  let total = 0;
  let startIndex = 1;
  for (let page = 0; page < 100; page += 1) {
    const response = await client.apiClient.request({
      path,
      method: 'GET',
      query: { count: 100, startIndex, attributes },
      headers: new Headers(),
      raw: false,
    }) as ScimListResponse<T>;
    const resources = response.Resources ?? [];
    total += resources.filter(predicate).length;
    startIndex += resources.length;
    if (!resources.length || startIndex > (response.totalResults ?? total)) return total;
  }
  throw new Error('SCIM pagination limit exceeded');
}

function withTimeout<T>(promise: Promise<T>, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${label} request timed out`)), REQUEST_TIMEOUT_MS);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });
}

function safeError(reason: unknown) {
  if (reason instanceof Error && /timed out/i.test(reason.message)) return reason.message;
  return 'The app service principal cannot access this metric';
}

export async function calculateWorkspaceStats(client: WorkspaceStatsClient): Promise<WorkspaceStatsResponse> {
  // Start each operation in its own promise so synchronous SDK errors are also
  // isolated by allSettled instead of failing the whole endpoint.
  const run = <T>(label: string, operation: () => Promise<T>) =>
    withTimeout(Promise.resolve().then(operation), label);
  const tasks = [
    run('Groups', () => countScimResources(client, '/api/2.0/preview/scim/v2/Groups', 'id')),
    run('Schemas', () => countSchemas(client)),
    run('Tables', () => countTables(client)),
    run('Apps', () => count(client.apps.list({ page_size: 100 }))),
    run('Lakebase', () => countLakebaseProjects(client)),
    run('Lakeflow jobs', () => count(client.jobs.list({ limit: 100, expand_tasks: false }))),
    run('Lakeflow pipelines', () => count(client.pipelines.listPipelines({ max_results: 100 }))),
  ];
  const results = await Promise.allSettled(tasks);
  const metric = (index: number): WorkspaceStat => {
    const result = results[index];
    return result.status === 'fulfilled'
      ? { value: result.value, status: 'available' }
      : { value: null, status: 'unavailable', error: safeError(result.reason) };
  };

  return {
    stats: {
      groups: metric(0),
      schemas: metric(1),
      tables: metric(2),
      apps: metric(3),
      lakebaseInstances: metric(4),
      lakeflowJobs: metric(5),
      lakeflowPipelines: metric(6),
    },
    calculatedAt: new Date().toISOString(),
  };
}

export async function getWorkspaceStats(client: WorkspaceStatsClient, forceRefresh = false) {
  const now = Date.now();
  if (!forceRefresh && cached && cached.expiresAt > now) return cached.response;
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = calculateWorkspaceStats(client).then((response) => {
    cached = { response, expiresAt: Date.now() + CACHE_TTL_MS };
    return response;
  }).finally(() => {
    refreshInFlight = undefined;
  });
  return refreshInFlight;
}

export function resetWorkspaceStatsCache() {
  cached = undefined;
  refreshInFlight = undefined;
}

export function setupWorkspaceStatsRoutes(app: Application) {
  // Default auth in a Databricks App is the app service principal. Never use
  // appkit.asUser() here: these are workspace/resource statistics, not OBO data.
  const client = createWorkspaceClient().toLegacyWorkspaceClient() as unknown as WorkspaceStatsClient;
  app.get('/api/workspace-stats', async (req, res) => {
    try {
      const forceRefresh = req.query.refresh === 'true';
      res.setHeader('Cache-Control', 'private, no-store');
      res.json(await getWorkspaceStats(client, forceRefresh));
    } catch (error) {
      console.error('Failed to calculate workspace stats', error);
      res.status(500).json({ error: 'Failed to calculate workspace stats' });
    }
  });
}
