import { createApp, lakebase, server } from '@databricks/appkit';
import { setupIssueRoutes } from './routes/issues';
import { setupWorkspaceStatsRoutes } from './routes/workspace-stats';

createApp({
  cache: { enabled: false },
  plugins: [
    lakebase(),
    server(),
  ],
  async onPluginsReady(appkit) {
    await setupIssueRoutes(appkit);
    appkit.server.extend(setupWorkspaceStatsRoutes);
  },
}).catch(console.error);
