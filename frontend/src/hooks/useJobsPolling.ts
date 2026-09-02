import { useCallback, useEffect, useState } from "react";
import { api, type Job } from "../api/client";

const POLL_MS = 5000;

export function useJobsPolling(intervalMs = POLL_MS) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.jobs();
      setJobs(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => {
      void refresh();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, refresh]);

  return { jobs, loading, error, refresh };
}
