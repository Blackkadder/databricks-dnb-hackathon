import { beforeEach, describe, expect, test, vi } from 'vitest';
import { calculateWorkspaceStats, getWorkspaceStats, resetWorkspaceStatsCache } from './workspace-stats';

function iterable<T>(values: T[]): AsyncIterable<T> {
  return { async *[Symbol.asyncIterator]() { yield* values; } };
}

function client(overrides: Record<string, unknown> = {}) {
  return {
    catalogs: { list: vi.fn(() => iterable([{ name: 'main' }, { name: 'system' }])) },
    schemas: { list: vi.fn(() => iterable([{ name: 'default' }, { name: 'information_schema' }])) },
    tables: { listSummaries: vi.fn(() => iterable([
      { table_type: 'MANAGED' }, { table_type: 'EXTERNAL' }, { table_type: 'VIEW' },
    ])) },
    apps: { list: vi.fn(() => iterable([{}, {}, {}])) },
    jobs: { list: vi.fn(() => iterable([{}, {}, {}, {}])) },
    pipelines: { listPipelines: vi.fn(() => iterable([{}, {}])) },
    apiClient: { request: vi.fn(async ({ path }: { path: string }) => {
      if (path.endsWith('/Users')) return { Resources: [{ active: true }, { active: false }, {}], totalResults: 3 };
      if (path.endsWith('/Groups')) return { Resources: [{}, {}], totalResults: 2 };
      return { projects: [{}] };
    }) },
    ...overrides,
  };
}

describe('workspace stats', () => {
  beforeEach(resetWorkspaceStatsCache);

  test('counts visible resources and excludes inactive users, system metadata, and views', async () => {
    const mockClient = client();
    const stats = await calculateWorkspaceStats(mockClient as never);

    expect(stats.stats.groups).toEqual({ value: 2, status: 'available' });
    expect(stats.stats.schemas).toEqual({ value: 1, status: 'available' });
    expect(mockClient.schemas.list).toHaveBeenCalledWith({
      catalog_name: 'hackathon',
      max_results: 0,
      include_browse: true,
    });
    expect(stats.stats.tables).toEqual({ value: 2, status: 'available' });
    expect(stats.stats.apps).toEqual({ value: 3, status: 'available' });
    expect(stats.stats.lakebaseInstances).toEqual({ value: 1, status: 'available' });
    expect(stats.stats.lakeflowJobs).toEqual({ value: 4, status: 'available' });
    expect(stats.stats.lakeflowPipelines).toEqual({ value: 2, status: 'available' });
  });

  test('paginates Lakebase projects', async () => {
    let lakebasePage = 0;
    const request = vi.fn(async ({ path }: { path: string }) => {
      if (path.endsWith('/Users')) return { Resources: [{ active: true }], totalResults: 1 };
      if (path.endsWith('/Groups')) return { Resources: [{}], totalResults: 1 };
      lakebasePage += 1;
      return lakebasePage === 1
        ? { projects: [{}, {}], next_page_token: 'next' }
        : { projects: [{}] };
    });
    const stats = await calculateWorkspaceStats(client({ apiClient: { request } }) as never);

    expect(stats.stats.lakebaseInstances).toEqual({ value: 3, status: 'available' });
    const lakebaseCalls = request.mock.calls.filter(([options]) => options.path === '/api/2.0/postgres/projects');
    expect(lakebaseCalls).toHaveLength(2);
    expect((lakebaseCalls[1]?.[0] as unknown as { query: { page_token?: string } }).query.page_token).toBe('next');
  });

  test('returns a partial response when an API is unavailable', async () => {
    const stats = await calculateWorkspaceStats(client({
      apiClient: { request: vi.fn(async ({ path }: { path: string }) => {
        if (path.endsWith('/Groups')) throw new Error('sensitive upstream detail');
        if (path.endsWith('/Users')) return { Resources: [{}], totalResults: 1 };
        return { projects: [{}] };
      }) },
    }) as never);

    expect(stats.stats.apps.status).toBe('available');
    expect(stats.stats.groups).toEqual({
      value: null,
      status: 'unavailable',
      error: 'The app service principal cannot access this metric',
    });
  });

  test('caches reads and coalesces a forced refresh already in flight', async () => {
    const mockClient = client();
    const first = await getWorkspaceStats(mockClient as never);
    const second = await getWorkspaceStats(mockClient as never);
    expect(second).toBe(first);
    expect(mockClient.apiClient.request).toHaveBeenCalledTimes(2);

    resetWorkspaceStatsCache();
    const [refreshA, refreshB] = await Promise.all([
      getWorkspaceStats(mockClient as never, true),
      getWorkspaceStats(mockClient as never, true),
    ]);
    expect(refreshB).toBe(refreshA);
    expect(mockClient.apiClient.request).toHaveBeenCalledTimes(4);
  });
});
