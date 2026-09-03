import { useCallback, useRef, useState } from "react";
import { usePageMeta } from "../hooks/usePageMeta";
import { useI18n } from "../i18n/context";
import {
  downloadBlob,
  exportDecisionTracePdf,
  fetchLiveOpsScenario,
  liveOpsNarrateStream,
  type AskEvalEvent,
  type AskFinalEvent,
  type LiveOpsContextEvent,
  type LiveOpsScenario,
} from "../api/client";
import { Markdown } from "../components/Markdown";
import { PageExplainer } from "../components/PageExplainer";
import { TemperatureChart } from "../components/TemperatureChart";

const STEP_ORDER = ["what_happened", "the_problem", "gso_solution"] as const;
type StepId = (typeof STEP_ORDER)[number];
type StepStatus = "pending" | "active" | "done" | "error";
type StepState = { title: string; status: StepStatus; text: string; error?: string };

const STEP_TITLES: Record<StepId, string> = {
  what_happened: "What Happened",
  the_problem: "The Problem",
  gso_solution: "GSO-Aligned Solution",
};

const dispositionColor: Record<string, string> = {
  accept: "bg-emerald-100 text-emerald-800",
  hold_for_qa: "bg-amber-100 text-amber-900",
  reject: "bg-red-100 text-red-800",
  insufficient_data: "bg-slate-100 text-slate-700",
};

function emptySteps(): Record<StepId, StepState> {
  return STEP_ORDER.reduce(
    (acc, id) => {
      acc[id] = { title: STEP_TITLES[id], status: "pending", text: "" };
      return acc;
    },
    {} as Record<StepId, StepState>,
  );
}

export function LiveOpsPage() {
  const { t } = useI18n();
  usePageMeta(`${t("liveops.title")} | GCC Cold-Chain AI`, t("liveops.subtitle"));

  const [scenario, setScenario] = useState<LiveOpsScenario | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioError, setScenarioError] = useState<string | null>(null);

  const [officerNote, setOfficerNote] = useState("");
  const [narrating, setNarrating] = useState(false);
  const [steps, setSteps] = useState<Record<StepId, StepState>>(emptySteps());
  const [context, setContext] = useState<LiveOpsContextEvent | null>(null);
  const [final, setFinal] = useState<AskFinalEvent | null>(null);
  const [evalResult, setEvalResult] = useState<AskEvalEvent | null>(null);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [rateLimitNotice, setRateLimitNotice] = useState<{ attempt: number; waitS: number } | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [expandedStep, setExpandedStep] = useState<StepId | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const resetNarration = useCallback(() => {
    setSteps(emptySteps());
    setContext(null);
    setFinal(null);
    setEvalResult(null);
    setFatalError(null);
    setRateLimitNotice(null);
    setRetryCount(0);
    setExpandedStep(null);
    setExportError(null);
  }, []);

  const generateScenario = useCallback(async () => {
    abortRef.current?.abort();
    setScenarioLoading(true);
    setScenarioError(null);
    resetNarration();
    setOfficerNote("");
    try {
      const s = await fetchLiveOpsScenario();
      setScenario(s);
    } catch (err) {
      setScenarioError(err instanceof Error ? err.message : String(err));
    } finally {
      setScenarioLoading(false);
    }
  }, [resetNarration]);

  const startNarration = useCallback(async () => {
    if (!scenario || narrating) return;
    resetNarration();
    setNarrating(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await liveOpsNarrateStream(
        scenario,
        officerNote.trim() || null,
        {
          onContext: (data) => setContext(data),
          onStepStart: (data) => {
            const id = data.id as StepId;
            setSteps((prev) => ({ ...prev, [id]: { ...prev[id], status: "active" } }));
          },
          onStepDelta: (data) => {
            const id = data.id as StepId;
            setSteps((prev) => ({ ...prev, [id]: { ...prev[id], text: prev[id].text + (data.delta ?? "") } }));
          },
          onStepDone: (data) => {
            const id = data.id as StepId;
            setSteps((prev) => ({ ...prev, [id]: { ...prev[id], status: "done", text: data.output ?? prev[id].text } }));
          },
          onStepError: (data) => {
            const id = data.id as StepId;
            setSteps((prev) => ({ ...prev, [id]: { ...prev[id], status: "error", error: data.error } }));
          },
          onRateLimited: (data) => {
            setRetryCount((c) => c + 1);
            setRateLimitNotice({ attempt: data.attempt, waitS: data.wait_s });
          },
          onEval: (data) => setEvalResult(data),
          onFinal: (data) => {
            setFinal(data);
            setRateLimitNotice(null);
          },
          onDone: () => setNarrating(false),
        },
        controller.signal,
      );
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setFatalError(err instanceof Error ? err.message : String(err));
      }
      setNarrating(false);
    }
  }, [scenario, officerNote, narrating, resetNarration]);

  const toggle = (id: StepId) => {
    if (id === "gso_solution" && final) return;
    setExpandedStep((prev) => (prev === id ? null : id));
  };

  const exportPdf = useCallback(async () => {
    if (!scenario || !final) return;
    setExporting(true);
    setExportError(null);
    try {
      const blob = await exportDecisionTracePdf({
        kind: "liveops",
        title: `${scenario.truck_id} · ${scenario.product} · ${scenario.fault_mode}`,
        jurisdiction: scenario.jurisdiction,
        product: scenario.product,
        meta_lines: [
          `Ambient: ${scenario.ambient_c ?? "n/a"}°C; days since production: ${scenario.days_since_production ?? "n/a"}`,
          `Peak reading: ${scenario.peak_temp_c ?? "n/a"}°C; excursion: ${scenario.excursion_minutes} cumulative minutes out of band`,
          `Deterministic disposition: ${scenario.disposition} via ${scenario.rule_id}`,
          ...(officerNote.trim() ? [`Officer note: ${officerNote.trim()}`] : []),
        ],
        steps: STEP_ORDER.map((id) => ({ id, title: STEP_TITLES[id], output: steps[id].text })),
        final_answer: final.answer,
        citation_eval: evalResult,
      });
      downloadBlob(blob, `liveops-${scenario.truck_id}-decision-trace.pdf`);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  }, [scenario, final, evalResult, steps, officerNote]);

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:py-14">
      <div className="max-w-2xl">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-gcc-navy/15 bg-gcc-sand px-3 py-1 text-xs font-semibold uppercase tracking-wide text-gcc-navy">
          <span className="h-1.5 w-1.5 rounded-full bg-gcc-gold" />
          {t("liveops.badge")}
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-gcc-navy sm:text-4xl">{t("liveops.title")}</h1>
        <p className="mt-3 leading-relaxed text-slate-600">{t("liveops.subtitle")}</p>
      </div>

      <PageExplainer whatKey="liveops.explainWhat" inputKey="liveops.explainInput" outputKey="liveops.explainOutput" />

      <div className="card mt-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-gcc-navy">{t("liveops.scenarioHeading")}</h2>
            <p className="mt-1 text-sm text-slate-500">{t("liveops.scenarioHint")}</p>
          </div>
          <button type="button" className="btn-primary" onClick={() => void generateScenario()} disabled={scenarioLoading}>
            {scenarioLoading ? t("liveops.generating") : t("liveops.generateButton")}
          </button>
        </div>

        {scenarioError && <p className="mt-3 text-sm text-red-600">{scenarioError}</p>}

        {scenario && (
          <div className="mt-5 space-y-4">
            <div className="rounded-xl border border-gcc-navy/15 bg-gcc-sand/30 p-4">
              <p className="text-sm font-semibold text-gcc-navy">{scenario.truck_id}</p>
              <p className="mt-1 text-sm leading-relaxed text-slate-700" dir="auto">
                {scenario.narrative_opening}
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-white px-2.5 py-1 font-medium text-slate-600 shadow-sm">{scenario.jurisdiction}</span>
                <span className="rounded-full bg-white px-2.5 py-1 font-medium text-slate-600 shadow-sm">{scenario.product}</span>
                <span className="rounded-full bg-white px-2.5 py-1 font-medium text-slate-600 shadow-sm">{scenario.fault_mode}</span>
                <span className={`rounded-full px-2.5 py-1 font-semibold ${dispositionColor[scenario.disposition] ?? "bg-slate-100 text-slate-700"}`}>
                  {scenario.disposition} ({scenario.rule_id})
                </span>
              </div>
            </div>

            <TemperatureChart
              readings={scenario.readings_c}
              bandMin={scenario.temp_band_min_c}
              bandMax={scenario.temp_band_max_c}
              intervalMin={scenario.interval_min}
            />

            <div className="grid gap-3 text-sm sm:grid-cols-3">
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-xs font-semibold uppercase text-slate-400">{t("liveops.excursion")}</p>
                <p className="mt-1 font-medium text-slate-800">{scenario.excursion_minutes} min</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-xs font-semibold uppercase text-slate-400">{t("liveops.peakTemp")}</p>
                <p className="mt-1 font-medium text-slate-800">{scenario.peak_temp_c ?? "n/a"}°C</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-xs font-semibold uppercase text-slate-400">{t("liveops.shelfDays")}</p>
                <p className="mt-1 font-medium text-slate-800">{scenario.remaining_shelf_days ?? "n/a"}</p>
              </div>
            </div>

            <label className="block text-sm">
              <span className="font-medium text-slate-700">{t("liveops.officerNoteLabel")}</span>
              <textarea
                dir="auto"
                className="mt-1.5 w-full resize-y rounded-xl border border-slate-200 bg-white px-3.5 py-3 leading-relaxed text-slate-800 shadow-sm transition focus:border-gcc-navy focus:outline-none focus:ring-2 focus:ring-gcc-gold/40"
                rows={2}
                placeholder={t("liveops.officerNotePlaceholder")}
                value={officerNote}
                onChange={(e) => setOfficerNote(e.target.value)}
              />
            </label>

            <button type="button" className="btn-primary w-full sm:w-auto" onClick={() => void startNarration()} disabled={narrating}>
              {narrating ? t("liveops.narrating") : t("liveops.narrateButton")}
            </button>
          </div>
        )}
      </div>

      {context && (
        <div className="mt-6 flex flex-wrap gap-2 text-xs text-slate-500">
          <span className="rounded-full bg-slate-100 px-2.5 py-1">
            {t("ask.groundedIn")}: {context.jurisdiction ?? t("ask.any")}
          </span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1">
            {t("ask.rulesMatched")}: {context.matched_rule_ids.length}
          </span>
        </div>
      )}

      {(narrating || final || fatalError) && (
        <div className="card mt-4">
          {rateLimitNotice && (
            <p className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {t("ask.rateLimited")} ({t("ask.retryAttempt")} {rateLimitNotice.attempt}, ~{Math.round(rateLimitNotice.waitS)}s)
            </p>
          )}

          <ol className="space-y-2">
            {STEP_ORDER.map((id, idx) => {
              const step = steps[id];
              const isExpanded = expandedStep === id || (step.status === "active" && expandedStep === null);
              return (
                <li key={id} className="rounded-xl border border-slate-100">
                  <button
                    type="button"
                    onClick={() => toggle(id)}
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left"
                  >
                    <span
                      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                        step.status === "done"
                          ? "bg-gcc-teal text-white"
                          : step.status === "active"
                            ? "bg-gcc-gold text-white"
                            : step.status === "error"
                              ? "bg-red-500 text-white"
                              : "bg-slate-100 text-slate-400"
                      }`}
                    >
                      {idx + 1}
                    </span>
                    <span className="flex-1 text-sm font-medium text-slate-800">{step.title}</span>
                  </button>
                  {isExpanded && (step.text || step.error) && (
                    <div className="border-t border-slate-100 px-3.5 py-3">
                      {step.error ? (
                        <p className="text-sm text-red-600">{step.error}</p>
                      ) : (
                        <Markdown text={step.text} className="text-sm text-slate-700" />
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>

          {fatalError && <p className="mt-3 text-sm text-red-600">{fatalError}</p>}

          {final && (
            <div className="mt-5 rounded-xl border border-gcc-navy/15 bg-gradient-to-b from-gcc-sand/40 to-white p-4 sm:p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-bold uppercase tracking-wide text-gcc-navy">{t("liveops.solution")}</p>
                <div className="flex items-center gap-2">
                  {evalResult && (
                    <span className={evalResult.all_verified ? "badge-ok" : "badge-warn"}>
                      {evalResult.all_verified
                        ? t("ask.citationsVerified")
                        : `${evalResult.unverified_rule_ids.length + evalResult.unverified_gso_codes.length} ${t("ask.citationsUnverified")}`}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => void exportPdf()}
                    disabled={exporting}
                    className="rounded-lg border border-gcc-navy/20 px-2.5 py-1 text-xs font-semibold text-gcc-navy hover:bg-gcc-sand"
                  >
                    {exporting ? t("common.exporting") : t("common.exportPdf")}
                  </button>
                </div>
              </div>
              <Markdown text={final.answer} className="text-sm text-slate-800" />
              {exportError && <p className="mt-2 text-xs text-red-600">{exportError}</p>}
              {evalResult && !evalResult.all_verified && (
                <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                  <p className="font-semibold">{t("ask.unverifiedWarning")}</p>
                  {evalResult.unverified_rule_ids.length > 0 && (
                    <p className="mt-1">
                      {t("ask.unverifiedRuleIds")}: {evalResult.unverified_rule_ids.join(", ")}
                    </p>
                  )}
                  {evalResult.unverified_gso_codes.length > 0 && (
                    <p className="mt-1">
                      {t("ask.unverifiedGsoCodes")}: {evalResult.unverified_gso_codes.map((c) => `GSO ${c}`).join(", ")}
                    </p>
                  )}
                </div>
              )}
              {retryCount > 0 && (
                <p className="mt-3 text-[11px] text-slate-400">
                  {retryCount} {t("ask.retriedNote")}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
