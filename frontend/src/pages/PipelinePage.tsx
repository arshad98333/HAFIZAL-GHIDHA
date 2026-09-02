import { usePageMeta } from "../hooks/usePageMeta";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useI18n } from "../i18n/context";

const stages = [
  { key: "plan", path: (w: number) => `/waves/${w}/plan`, labelKey: "pipeline.plan" },
  { key: "generate", path: (w: number) => `/waves/${w}/generate`, labelKey: "pipeline.generate", body: {} },
  { key: "gate-a", path: (w: number) => `/waves/${w}/gate-a`, labelKey: "pipeline.gateA" },
  { key: "preflight", path: (w: number) => `/waves/${w}/preflight`, labelKey: "pipeline.preflight", sync: true },
] as const;

export function PipelinePage() {
  const { t } = useI18n();
  usePageMeta(`${t("pipeline.title")} | GCC Cold-Chain AI`);
  const [wave, setWave] = useState(1);
  const [lastJob, setLastJob] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run(stage: (typeof stages)[number]) {
    setBusy(stage.key);
    setErr(null);
    try {
      const path = stage.path(wave);
      const bg = "sync" in stage && stage.sync ? "?background=false" : "";
      const job = await api.post(`${path}${bg}`, "body" in stage ? stage.body : undefined);
      setLastJob(job.job_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
        <h1 className="text-3xl font-bold text-gcc-navy">{t("pipeline.title")}</h1>
        <p className="mt-2 text-slate-600">{t("pipeline.subtitle")}</p>

        <div className="mt-6">
          <label className="text-sm">
            {t("dashboard.wave")}
            <input
              type="number"
              min={1}
              value={wave}
              onChange={(e) => setWave(Number(e.target.value))}
              className="ms-2 w-16 rounded border px-2 py-1"
            />
          </label>
        </div>

        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {stages.map((s) => (
            <button
              key={s.key}
              type="button"
              disabled={busy !== null}
              onClick={() => run(s)}
              className="card text-start transition hover:border-gcc-navy/30 hover:shadow-md disabled:opacity-50"
            >
              <span className="font-semibold text-gcc-navy">{t(s.labelKey)}</span>
              {busy === s.key && <span className="ms-2 text-sm text-slate-400">…</span>}
            </button>
          ))}
        </div>

        <p className="mt-6 text-sm text-slate-500">{t("pipeline.rescoreHint")}</p>

        {err && <p className="mt-4 text-red-600">{err}</p>}
        {lastJob && (
          <p className="mt-4">
            {t("pipeline.started")}:{" "}
            <Link to="/jobs" className="font-mono text-gcc-navy underline">
              {lastJob}
            </Link>
          </p>
        )}
      </div>
  );
}
