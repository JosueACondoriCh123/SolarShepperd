import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api";

export function useApi<T>(
  loader: () => Promise<T>,
  dependencies: unknown[] = [],
  pollMs?: number,
  enabled = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const value = await loader();
      setData(value);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : new ApiError("NETWORK_ERROR", String(reason)));
    } finally {
      setLoading(false);
    }
  }, dependencies); // eslint-disable-line react-hooks/exhaustive-deps -- the caller owns this hook's dependency contract

  useEffect(() => {
    if (!enabled) {
      setData(null);
      setError(null);
      setLoading(false);
      return undefined;
    }
    void reload();
    if (!pollMs) return undefined;
    const timer = window.setInterval(() => void reload(), pollMs);
    return () => window.clearInterval(timer);
  }, [enabled, reload, pollMs]);

  return { data, error, loading, reload };
}
