import { useCallback, useEffect, useState } from "react";

export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    loader().then((value) => { setData(value); setError(""); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load data."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

export function Loading({ error }: { error?: string }) {
  return error ? <div className="notice error">{error}</div> : <div className="loading">Loading…</div>;
}

