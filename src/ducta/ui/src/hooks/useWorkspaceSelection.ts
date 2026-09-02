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
/**
 * What the client can determine about the source without asking the server:
 * an explicit `?source=`, a previously stored one, or the sandbox default.
 *
 * Pure — reads only. `resolved: false` means the caller must fall back to the
 * server's auto-detect endpoint.
 */
function resolveKnownSource(): {
  source: string | null;
  resolved: boolean;
  persist: boolean;
  remember: boolean;
} {
  const params = new URLSearchParams(globalThis.location.search);
  const fromUrl = normalizeSourceInput(params.get('source'));
  if (fromUrl) return { source: fromUrl, resolved: true, persist: true, remember: true };

  const stored = normalizeSourceInput(StorageService.getSource());
  if (stored) return { source: stored, resolved: true, persist: false, remember: false };

  if (getRuntimeMode() === 'sandbox') {
    // Sandbox/local demo mode only.
    return { source: SANDBOX_DEFAULT_SOURCE, resolved: true, persist: true, remember: false };
  }

  return { source: null, resolved: false, persist: false, remember: false };
}

export const useSourceSelection = () => {
  // The URL param, storage and runtime mode are all synchronous reads, so the
  // source they imply is known before the first paint. Resolving it in a lazy
  // initialiser instead of an effect removes a render spent in a `isLoading`
  // state that was never actually pending, and keeps the three setState calls
  // out of the effect body.
  const [initial] = useState(resolveKnownSource);
  const [selectedSource, setSelectedSource] = useState<string | null>(initial.source);
  const [isLoading, setIsLoading] = useState<boolean>(!initial.resolved);

  useEffect(() => {
    // Persisting what we resolved is a write, so it belongs here rather than in
    // the initialiser above.
    if (initial.resolved) {
      if (initial.persist && initial.source) {
        StorageService.setSource(initial.source);
        if (initial.remember) StorageService.addRecentSource(initial.source);
      }
      return;
    }

    {
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
  }, [initial]);

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
