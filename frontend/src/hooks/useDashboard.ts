import { useCallback } from "react";
import { api, type WaveAudit } from "../api/client";
import { useAsyncRequest } from "./useAsyncRequest";

export type DashboardSnapshot = {
  health: string;
  ready: string;
  audit: WaveAudit | null;
};

export function useDashboard(wave: number) {
  const request = useCallback(async (): Promise<DashboardSnapshot> => {
    const [health, ready, audit] = await Promise.all([
      api.health().catch(() => ({ status: "error" })),
      api.ready().catch(() => ({ status: "not_ready" })),
      api.audit(wave).catch(() => null),
    ]);
    return {
      health: health.status,
      ready: ready.status,
      audit,
    };
  }, [wave]);

  return useAsyncRequest(request, [wave]);
}
