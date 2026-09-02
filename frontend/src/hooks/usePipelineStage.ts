import { useCallback, useState } from "react";
import { api } from "../api/client";

export function usePipelineStage(wave: number) {
  const [busy, setBusy] = useState<string | null>(null);
  const [lastJobId, setLastJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runStage = useCallback(
    async (stageKey: string, path: string, body?: unknown, sync = false) => {
      setBusy(stageKey);
      setError(null);
      try {
        const suffix = sync ? "?background=false" : "";
        const job = await api.post(`${path}${suffix}`, body);
        setLastJobId(job.job_id);
        return job;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        return null;
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  return { wave, busy, lastJobId, error, runStage };
}
