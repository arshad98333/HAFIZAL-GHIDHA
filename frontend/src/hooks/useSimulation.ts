import { useCallback, useEffect, useState } from "react";
import { api, type SimulateResult } from "../api/client";

export type SimulationInput = {
  product: string;
  fault_mode: string;
  jurisdiction: string;
  artifact_type: string;
  seed: number;
};

export function useSimulation(initial: SimulationInput, options?: { runOnMount?: boolean }) {
  const [input, setInput] = useState<SimulationInput>(initial);
  const [result, setResult] = useState<SimulateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (override?: Partial<SimulationInput>) => {
    const payload = { ...input, ...override };
    setLoading(true);
    setError(null);
    try {
      const data = await api.simulate(payload);
      setResult(data);
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [input]);

  useEffect(() => {
    if (options?.runOnMount) {
      void run();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    input,
    setInput,
    result,
    loading,
    error,
    run,
  };
}
