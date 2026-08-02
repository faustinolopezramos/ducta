import { useEffect, useState } from 'react';
import { StorageService } from '../utils/storage';
import { normalizeSourceInput } from '../utils/sourcePath';

const SANDBOX_DEFAULT_SOURCE = './source/ducta_example_yml';

function getRuntimeMode() {
  return (import.meta.env.VITE_SOURCE_RUNTIME ?? import.meta.env.MODE ?? 'development')
    .toLowerCase();
}

/**
 * Hook to manage source selection and storage.
 * Stores the selected source in localStorage for persistence.
 */
export const useSourceSelection = () => {
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    const runtimeMode = getRuntimeMode();
    const isSandboxRuntime = runtimeMode === 'sandbox';
    const stored = StorageService.getSource();

    // Check URL params
    const params = new URLSearchParams(globalThis.location.search);
    const pathParam = params.get('source');

    const normalizedParam = normalizeSourceInput(pathParam);
    const normalizedStored = normalizeSourceInput(stored);

    if (normalizedParam) {
      setSelectedSource(normalizedParam);
      StorageService.setSource(normalizedParam);
      StorageService.addRecentSource(normalizedParam);
      setIsLoading(false);
    } else if (normalizedStored) {
      setSelectedSource(normalizedStored);
      setIsLoading(false);
    } else if (isSandboxRuntime) {
      // Sandbox/local demo mode only.
      setSelectedSource(SANDBOX_DEFAULT_SOURCE);
      StorageService.setSource(SANDBOX_DEFAULT_SOURCE);
      setIsLoading(false);
    } else {
      // Ask the server whether it was launched with `ducta ui` from a project directory.
      // The server sets DUCTA_WORKSPACE when auto-detecting or receiving --source.
      fetch('/api/workspace/auto-detect')
        .then((res) => (res.ok ? res.json() : null))
        .then((data: { path?: string } | null) => {
          if (data?.path) {
            const detected = normalizeSourceInput(data.path) ?? data.path;
            setSelectedSource(detected);
            StorageService.setSource(detected);
            StorageService.addRecentSource(detected);
          } else {
            setSelectedSource(null);
          }
        })
        .catch(() => {
          setSelectedSource(null);
        })
        .finally(() => {
          setIsLoading(false);
        });
    }
  }, []);

  const updateSource = (newSource: string | null) => {
    const normalizedSource = normalizeSourceInput(newSource);

    if (!normalizedSource) {
      setSelectedSource(null);
      StorageService.clearSource();
      return;
    }

    setSelectedSource(normalizedSource);
    StorageService.setSource(normalizedSource);
    StorageService.addRecentSource(normalizedSource);
    // Update URL
    const params = new URLSearchParams(globalThis.location.search);
    params.set('source', normalizedSource);
    globalThis.history.replaceState({}, '', `?${params.toString()}`);
  };

  return {
    selectedSource,
    isLoading,
    updateSource,
  };
};

// Export an alias for backward compatibility with unmigrated components
export const useWorkspaceSelection = useSourceSelection;
