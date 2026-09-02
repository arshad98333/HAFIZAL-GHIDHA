import { useState } from "react";
import { usePageMeta } from "../hooks/usePageMeta";
import { useDashboard } from "../hooks/useDashboard";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useI18n } from "../i18n/context";
import { EMPTY_VALUE } from "../lib/constants";

export function DashboardPage() {
  const { t } = useI18n();
  usePageMeta(`${t("dashboard.title")} | GCC Cold-Chain AI`);
  const [wave, setWave] = useState(1);
  const { data, loading, error, reload } = useDashboard(wave);

  const health = data?.health ?? EMPTY_VALUE;
  const ready = data?.ready ?? EMPTY_VALUE;
  const audit = data?.audit ?? null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-bold text-gcc-navy">{t("dashboard.title")}</h1>
        <div className="flex items-center gap-3">
          <label className="text-sm text-slate-600">
            {t("dashboard.wave")}
            <input
              type="number"
              min={1}
              value={wave}
              onChange={(e) => setWave(Number(e.target.value))}
              className="ms-2 w-16 rounded border border-slate-300 px-2 py-1"
            />
          </label>
          <button type="button" onClick={() => void reload()} className="btn-secondary">
            {t("dashboard.refresh")}
          </button>
        </div>
      </div>

      <p className="mt-2 text-sm text-slate-500">
        {t("dashboard.apiBase")}: <code className="rounded bg-slate-100 px-1">{api.baseUrl}</code>
      </p>

      {error && (
        <div className="mt-4 rounded-lg bg-red-50 p-4 text-red-800">
          {t("common.error")}: {error}
        </div>
      )}

      {loading ? (
        <p className="mt-8 text-slate-500">{t("common.loading")}</p>
      ) : (
        <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <div className="card">
            <p className="text-sm text-slate-500">{t("dashboard.health")}</p>
            <p className="mt-2 text-xl font-semibold">
              <span className={health === "ok" ? "badge-ok" : "badge-fail"}>{health}</span>
            </p>
          </div>
          <div className="card">
            <p className="text-sm text-slate-500">{t("dashboard.ready")}</p>
            <p className="mt-2 text-xl font-semibold">
              <span className={ready === "ready" ? "badge-ok" : "badge-warn"}>{ready}</span>
            </p>
          </div>
          <div className="card">
            <p className="text-sm text-slate-500">{t("dashboard.records")}</p>
            <p className="mt-2 text-2xl font-bold text-gcc-navy">{audit?.generation_log_rows ?? EMPTY_VALUE}</p>
            <p className="text-sm text-slate-500">
              {t("dashboard.kept")}: {audit?.kept_records ?? EMPTY_VALUE}
            </p>
          </div>
          <div className="card">
            <p className="text-sm text-slate-500">{t("dashboard.gateA")}</p>
            <p className="mt-2">
              {audit?.gate_a_passed === true && <span className="badge-ok">{t("dashboard.passed")}</span>}
              {audit?.gate_a_passed === false && <span className="badge-fail">{t("dashboard.failed")}</span>}
              {audit?.gate_a_passed == null && <span className="text-slate-400">{EMPTY_VALUE}</span>}
            </p>
          </div>
        </div>
      )}

      {audit?.gate_a_metrics && (
        <div className="card mt-8">
          <h2 className="font-semibold text-gcc-navy">{t("dashboard.metrics")}</h2>
          <dl className="mt-4 grid gap-2 sm:grid-cols-2">
            {Object.entries(audit.gate_a_metrics).map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-slate-100 py-2 text-sm">
                <dt className="text-slate-600">{k}</dt>
                <dd className="font-mono font-medium">{typeof v === "number" ? v.toFixed(4) : String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="mt-8">
        <Link to="/pipeline" className="btn-primary">
          {t("dashboard.viewPipeline")}
        </Link>
      </div>
    </div>
  );
}
