import { FormEvent } from "react";
import { usePageMeta } from "../hooks/usePageMeta";
import { useSimulation } from "../hooks/useSimulation";
import { useI18n } from "../i18n/context";
import { TemperatureChart } from "../components/TemperatureChart";
import { PageExplainer } from "../components/PageExplainer";

const PRODUCTS = ["finfish_seafood", "table_eggs", "chilled_dairy", "frozen_goods"] as const;
const FAULTS = ["in_spec", "door_open", "compressor_fail", "setpoint_drift", "sensor_artifact"] as const;
const JURISDICTIONS = ["AE", "SA", "QA", "BH", "KW", "OM"] as const;
const ARTIFACTS = ["logger_csv", "chat_message", "qc_form_ocr", "voice_note"] as const;

const dispositionColor: Record<string, string> = {
  accept: "bg-emerald-100 text-emerald-800",
  hold_for_qa: "bg-amber-100 text-amber-900",
  reject: "bg-red-100 text-red-800",
  insufficient_data: "bg-slate-100 text-slate-700",
};

export function SimulationPage() {
  const { t } = useI18n();
  usePageMeta(t("simulation.seoTitle"), t("simulation.seoDesc"));

  const { input, setInput, result, loading, error, run } = useSimulation(
    {
      product: "finfish_seafood",
      fault_mode: "door_open",
      jurisdiction: "AE",
      artifact_type: "logger_csv",
      seed: 42,
    },
    { runOnMount: true },
  );

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void run();
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="max-w-2xl">
        <h1 className="text-3xl font-bold text-gcc-navy">{t("simulation.title")}</h1>
        <p className="mt-3 text-slate-600 leading-relaxed">{t("simulation.subtitle")}</p>
      </div>

      <PageExplainer whatKey="simulation.explainWhat" inputKey="simulation.explainInput" outputKey="simulation.explainOutput" />

      <form onSubmit={onSubmit} className="mt-8 grid gap-6 lg:grid-cols-[320px_1fr]">
        <fieldset className="card space-y-4">
          <legend className="text-sm font-semibold text-gcc-navy">{t("simulation.inputs")}</legend>

          <label className="block text-sm">
            <span className="font-medium text-slate-700">{t("simulation.product")}</span>
            <select
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2"
              value={input.product}
              onChange={(e) => setInput({ ...input, product: e.target.value })}
            >
              {PRODUCTS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="font-medium text-slate-700">{t("simulation.fault")}</span>
            <select
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2"
              value={input.fault_mode}
              onChange={(e) => setInput({ ...input, fault_mode: e.target.value })}
            >
              {FAULTS.map((f) => (
                <option key={f} value={f}>
                  {t(`simulation.faults.${f}`)}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="font-medium text-slate-700">{t("simulation.jurisdiction")}</span>
            <select
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2"
              value={input.jurisdiction}
              onChange={(e) => setInput({ ...input, jurisdiction: e.target.value })}
            >
              {JURISDICTIONS.map((j) => (
                <option key={j} value={j}>
                  {j}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="font-medium text-slate-700">{t("simulation.artifact")}</span>
            <select
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2"
              value={input.artifact_type}
              onChange={(e) => setInput({ ...input, artifact_type: e.target.value })}
            >
              {ARTIFACTS.map((a) => (
                <option key={a} value={a}>
                  {t(`simulation.artifacts.${a}`)}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="font-medium text-slate-700">{t("simulation.seed")}</span>
            <input
              type="number"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2"
              value={input.seed}
              onChange={(e) => setInput({ ...input, seed: Number(e.target.value) })}
            />
          </label>

          <button type="submit" className="btn-primary w-full" disabled={loading}>
            {loading ? t("common.loading") : t("simulation.run")}
          </button>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </fieldset>

        <div className="space-y-6">
          {!result && !loading && (
            <div className="card border-dashed border-slate-300 bg-slate-50 text-center text-slate-500">
              {t("simulation.empty")}
            </div>
          )}

          {result && (
            <>
              <div className="card">
                <div className="flex flex-wrap items-center gap-3">
                  <span
                    className={`rounded-full px-3 py-1 text-sm font-semibold uppercase ${dispositionColor[result.disposition] ?? dispositionColor.insufficient_data}`}
                  >
                    {result.disposition.replace(/_/g, " ")}
                  </span>
                  <span className="text-sm text-slate-600">
                    {result.rule_id} | {result.excursion_minutes} min excursion | peak {result.peak_temp_c} C
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-500">{result.spec_clause}</p>
                <div className="mt-6">
                  <TemperatureChart
                    readings={result.readings_c}
                    bandMin={result.temp_band_min_c}
                    bandMax={result.temp_band_max_c}
                    intervalMin={result.interval_min}
                  />
                </div>
              </div>

              <div className="card">
                <h2 className="font-semibold text-gcc-navy">{t("simulation.pipeline")}</h2>
                <ol className="mt-4 space-y-3">
                  {result.steps.map((step, i) => (
                    <li key={step.id} className="flex gap-3 text-sm">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gcc-navy text-xs font-bold text-white">
                        {i + 1}
                      </span>
                      <div>
                        <p className="font-medium text-slate-800">{step.title}</p>
                        <p className="text-slate-600">{step.detail}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>

              <div className="grid gap-6 lg:grid-cols-2">
                <div className="card">
                  <h2 className="font-semibold text-gcc-navy">{t("simulation.artifactPreview")}</h2>
                  <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100 whitespace-pre-wrap">
                    {result.artifact_preview}
                  </pre>
                </div>
                <div className="card">
                  <h2 className="font-semibold text-gcc-navy">{t("simulation.renderPrompt")}</h2>
                  <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700 whitespace-pre-wrap border border-slate-200">
                    {result.render_prompt}
                  </pre>
                </div>
              </div>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
