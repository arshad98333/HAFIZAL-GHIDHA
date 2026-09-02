import { useCallback, useEffect, useState } from "react";

export type AsyncStatus = "idle" | "loading" | "success" | "error";

type Options = {
  enabled?: boolean;
  initialData?: null;
};

export function useAsyncRequest<T>(
  request: () => Promise<T>,
  deps: readonly unknown[],
  options: Options = {},
) {
  const { enabled = true, initialData = null } = options;
  const [data, setData] = useState<T | null>(initialData);
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const execute = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const result = await request();
      setData(result);
      setStatus("success");
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setStatus("error");
      return null;
    }
    // deps are forwarded from the caller (wave, inputs, etc.)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!enabled) return;
    void execute();
  }, [enabled, execute]);

  return {
    data,
    status,
    error,
    loading: status === "loading",
    reload: execute,
  };
}
