import {
  ResourceStatusIndicator,
  ResourceStatusProvider,
} from '@databricks/appkit-ui/react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.tsx';
import { ErrorBoundary } from './ErrorBoundary.tsx';

// This support app intentionally uses one consistent, accessible light theme.
document.documentElement.classList.remove('dark');
document.documentElement.dataset.theme = 'light';
document.documentElement.style.colorScheme = 'light';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      {/*
       * Surfaces resource readiness (e.g. SQL warehouse cold-starts) as a
       * single sonner toast across the whole tree. Both are no-ops when
       * nothing's pending; remove them to render the aggregate yourself
       * via useResourceStatus(). Apps that already mount their own
       * <Toaster /> can swap the indicator for useResourceStatusToaster().
       */}
      <ResourceStatusProvider>
        <ResourceStatusIndicator />
        <App />
      </ResourceStatusProvider>
    </ErrorBoundary>
  </StrictMode>
);
