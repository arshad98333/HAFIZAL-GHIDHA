import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { usePageMeta } from "../hooks/usePageMeta";
import { useI18n } from "../i18n/context";
import {
  askComplianceStream,
  downloadBlob,
  exportDecisionTracePdf,
  type AskContextEvent,
  type AskEvalEvent,
  type AskFinalEvent,
} from "../api/client";
import { Markdown } from "../components/Markdown";
import { PageExplainer } from "../components/PageExplainer";

const JURISDICTIONS = ["AE", "SA", "QA", "BH", "KW", "OM"] as const;
const PRODUCTS = ["finfish_seafood", "table_eggs", "chilled_dairy", "frozen_goods"] as const;

const STEP_ORDER = [
  "intent_extraction",
  "constraint_mapping",
  "counterfactual_analysis",
  "final_synthesis",
] as const;
type StepId = (typeof STEP_ORDER)[number];
type StepStatus = "pending" | "active" | "done" | "error";

type StepState = { title: string; status: StepStatus; text: string; error?: string };

type ChatTurn = {
  id: string;
  question: string;
  jurisdiction: string;
  product: string;
  context: AskContextEvent | null;
  steps: Record<StepId, StepState>;
  final: AskFinalEvent | null;
  evalResult: AskEvalEvent | null;
  fatalError: string | null;
  streaming: boolean;
  retryCount: number;
  rateLimitNotice: { attempt: number; waitS: number } | null;
  expandedStep: StepId | null;
};

function emptySteps(titles: Record<StepId, string>): Record<StepId, StepState> {
  return STEP_ORDER.reduce(
    (acc, id) => {
      acc[id] = { title: titles[id], status: "pending", text: "" };
      return acc;
    },
    {} as Record<StepId, StepState>,
  );
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "done") {
    return (
      <svg viewBox="0 0 20 20" fill="none" className="h-3.5 w-3.5">
        <path d="M4 10.5l3.5 3.5L16 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === "error") {
    return (
      <svg viewBox="0 0 20 20" fill="none" className="h-3.5 w-3.5">
        <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  if (status === "active") {
    return <span className="block h-2 w-2 rounded-full bg-white" />;
  }
  return <span className="block h-1.5 w-1.5 rounded-full bg-slate-400" />;
}

const stepCircleClass: Record<StepStatus, string> = {
  pending: "bg-slate-100 text-slate-400 border border-slate-300",
  active: "bg-gcc-gold text-white border border-gcc-gold shadow-[0_0_0_4px_rgba(196,163,90,0.2)]",
  done: "bg-emerald-600 text-white border border-emerald-600",
  error: "bg-red-600 text-white border border-red-600",
};

const stepLineClass: Record<StepStatus, string> = {
  pending: "bg-slate-200",
  active: "bg-slate-200",
  done: "bg-emerald-500",
  error: "bg-red-300",
};

export function AskPage() {
  const { t, dir } = useI18n();
  usePageMeta(t("ask.seoTitle"), t("ask.seoDesc"));

  const stepTitles = {
    intent_extraction: t("ask.steps.intent_extraction"),
    constraint_mapping: t("ask.steps.constraint_mapping"),
    counterfactual_analysis: t("ask.steps.counterfactual_analysis"),
    final_synthesis: t("ask.steps.final_synthesis"),
  } as Record<StepId, string>;

  const [question, setQuestion] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [product, setProduct] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const patchTurn = useCallback((id: string, patch: Partial<ChatTurn>) => {
    setTurns((prev) => prev.map((tn) => (tn.id === id ? { ...tn, ...patch } : tn)));
  }, []);

  const patchStep = useCallback((id: string, stepId: string, patch: Partial<StepState>) => {
    setTurns((prev) =>
      prev.map((tn) =>
        tn.id === id
          ? {
              ...tn,
              rateLimitNotice: null,
              steps: { ...tn.steps, [stepId]: { ...tn.steps[stepId as StepId], ...patch } },
            }
          : tn,
      ),
    );
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || sending) return;

    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const turn: ChatTurn = {
      id,
      question: q,
      jurisdiction,
      product,
      context: null,
      steps: emptySteps(stepTitles),
      final: null,
      evalResult: null,
      fatalError: null,
      streaming: true,
      retryCount: 0,
      rateLimitNotice: null,
      expandedStep: null,
    };
    setTurns((prev) => [turn, ...prev]);
    setQuestion("");
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await askComplianceStream(
        { question: q, jurisdiction: jurisdiction || null, product: product || null },
        {
          onContext: (data) => patchTurn(id, { context: data }),
          onStepStart: (data) => patchStep(id, data.id, { status: "active", text: "" }),
          onStepDelta: (data) => {
            setTurns((prev) =>
              prev.map((tn) => {
                if (tn.id !== id) return tn;
                const step = tn.steps[data.id as StepId];
                return {
                  ...tn,
                  rateLimitNotice: null,
                  steps: { ...tn.steps, [data.id]: { ...step, text: step.text + (data.delta || "") } },
                };
              }),
            );
          },
          onStepDone: (data) =>
            patchStep(id, data.id, { status: "done", text: data.output ?? undefined }),
          onStepError: (data) => patchStep(id, data.id, { status: "error", error: data.error }),
          onRateLimited: (data) =>
            setTurns((prev) =>
              prev.map((tn) =>
                tn.id === id
                  ? {
                      ...tn,
                      retryCount: tn.retryCount + 1,
                      rateLimitNotice: { attempt: data.attempt, waitS: data.wait_s },
                    }
                  : tn,
              ),
            ),
          onEval: (data) => patchTurn(id, { evalResult: data }),
          onFinal: (data) => patchTurn(id, { final: data, expandedStep: null }),
          onDone: () => patchTurn(id, { streaming: false, rateLimitNotice: null }),
        },
        controller.signal,
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      patchTurn(id, { fatalError: message, streaming: false, rateLimitNotice: null });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:py-14">
      <div className="max-w-2xl">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-gcc-navy/15 bg-gcc-sand px-3 py-1 text-xs font-semibold uppercase tracking-wide text-gcc-navy">
          <span className="h-1.5 w-1.5 rounded-full bg-gcc-gold" />
          {t("landing.jurisdictions")}
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-gcc-navy sm:text-4xl">{t("ask.title")}</h1>
        <p className="mt-3 leading-relaxed text-slate-600">{t("ask.subtitle")}</p>
      </div>

      <PageExplainer whatKey="ask.explainWhat" inputKey="ask.explainInput" outputKey="ask.explainOutput" />

      <form onSubmit={onSubmit} className="card mt-8 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="font-medium text-slate-700">{t("ask.jurisdiction")}</span>
            <select
              className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-slate-800 shadow-sm transition focus:border-gcc-navy focus:outline-none focus:ring-2 focus:ring-gcc-gold/40"
              value={jurisdiction}
              onChange={(e) => setJurisdiction(e.target.value)}
            >
              <option value="">{t("ask.any")}</option>
              {JURISDICTIONS.map((j) => (
                <option key={j} value={j}>
                  {j}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-medium text-slate-700">{t("ask.product")}</span>
            <select
              className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-slate-800 shadow-sm transition focus:border-gcc-navy focus:outline-none focus:ring-2 focus:ring-gcc-gold/40"
              value={product}
              onChange={(e) => setProduct(e.target.value)}
            >
              <option value="">{t("ask.any")}</option>
              {PRODUCTS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="block text-sm">
          <textarea
            ref={textareaRef}
            dir="auto"
            className="mt-1.5 w-full resize-y rounded-xl border border-slate-200 bg-white px-3.5 py-3 leading-relaxed text-slate-800 shadow-sm transition focus:border-gcc-navy focus:outline-none focus:ring-2 focus:ring-gcc-gold/40"
            rows={3}
            placeholder={t("ask.placeholder")}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void onSubmit(e as unknown as FormEvent);
              }
            }}
          />
        </label>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">{t("ask.disclaimer")}</p>
          <button type="submit" className="btn-primary shrink-0" disabled={sending || !question.trim()}>
            {sending ? (
              <span className="flex items-center gap-2">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                {t("ask.sending")}
              </span>
            ) : (
              t("ask.send")
            )}
          </button>
        </div>
      </form>

      <div className="mt-10 space-y-6">
        {turns.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/60 px-6 py-10 text-center text-sm text-slate-500">
            {t("ask.empty")}
          </div>
        )}
        {turns.map((turn) => (
          <ChatTurnCard key={turn.id} turn={turn} t={t} dir={dir} onToggleStep={patchTurn} />
        ))}
      </div>
    </div>
  );
}

function ChatTurnCard({
  turn,
  t,
  onToggleStep,
}: {
  turn: ChatTurn;
  t: (k: string) => string;
  dir: "ltr" | "rtl";
  onToggleStep: (id: string, patch: Partial<ChatTurn>) => void;
}) {
  const toggle = (stepId: StepId) => {
    // The final_synthesis step's raw output IS the final answer -- once
    // turn.final is set, that text is already shown prominently in the
    // Answer card below, so expanding this step here would just duplicate
    // it verbatim. Steps 1-3 (the actual reasoning trail) stay expandable.
    if (stepId === "final_synthesis" && turn.final) return;
    onToggleStep(turn.id, { expandedStep: turn.expandedStep === stepId ? null : stepId });
  };

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportPdf = async () => {
    if (!turn.final) return;
    setExporting(true);
    setExportError(null);
    try {
      const blob = await exportDecisionTracePdf({
        kind: "ask",
        title: turn.question,
        jurisdiction: turn.context?.jurisdiction ?? turn.jurisdiction ?? null,
        product: turn.context?.product ?? turn.product ?? null,
        meta_lines: turn.context
          ? [`Retrieved rule IDs: ${turn.context.matched_rule_ids.join(", ") || "none"}`]
          : [],
        steps: STEP_ORDER.map((id) => ({ id, title: turn.steps[id].title, output: turn.steps[id].text })),
        final_answer: turn.final.answer,
        citation_eval: turn.evalResult,
      });
      downloadBlob(blob, `ask-decision-trace-${turn.id}.pdf`);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
      {/* question */}
      <div className="border-b border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-6">
        <p dir="auto" className="font-medium leading-relaxed text-slate-800">
          {turn.question}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-gcc-navy ring-1 ring-inset ring-gcc-navy/15">
            {turn.jurisdiction || t("ask.any")}
          </span>
          <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-gcc-navy ring-1 ring-inset ring-gcc-navy/15">
            {turn.product || t("ask.any")}
          </span>
          {turn.context && (
            <span className="text-[11px] text-slate-500">
              {t("ask.groundedIn")} {turn.context.matched_rule_ids.length} {t("ask.rulesMatched")}
              {!turn.context.has_citation && turn.context.jurisdiction ? ` · ${t("ask.noCitation")}` : ""}
            </span>
          )}
          {turn.context?.product_mismatch && (
            <span className="rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
              {t("ask.productMismatchPrefix")} {turn.context.product} {t("ask.productMismatchSuffix")}
            </span>
          )}
        </div>
      </div>

      <div className="px-5 py-5 sm:px-6">
        {turn.fatalError && (
          <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{turn.fatalError}</p>
        )}

        {turn.rateLimitNotice && (
          <div className="mb-4 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
            <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-amber-500" />
            {t("ask.rateLimited")} · {t("ask.retryAttempt")} {turn.rateLimitNotice.attempt} ·{" "}
            {Math.ceil(turn.rateLimitNotice.waitS)}s
          </div>
        )}

        {/* stepper */}
        <div className="flex items-start">
          {STEP_ORDER.map((stepId, i) => {
            const step = turn.steps[stepId];
            const isExpanded = turn.expandedStep === stepId;
            const isAnswerStep = stepId === "final_synthesis" && !!turn.final;
            return (
              <div key={stepId} className={`flex items-start ${i < STEP_ORDER.length - 1 ? "flex-1" : ""}`}>
                <button
                  type="button"
                  onClick={() => toggle(stepId)}
                  className={`group flex w-16 flex-col items-center gap-1.5 text-center sm:w-20 ${isAnswerStep ? "cursor-default" : ""}`}
                  title={isAnswerStep ? `${step.title} \u2014 ${t("ask.answer")}` : step.title}
                >
                  <span
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition ${stepCircleClass[step.status]} ${isExpanded ? "ring-2 ring-gcc-gold ring-offset-2" : ""}`}
                  >
                    <StepIcon status={step.status} />
                  </span>
                  <span
                    className={`line-clamp-2 text-[10.5px] font-medium leading-tight ${isExpanded ? "text-gcc-navy" : "text-slate-500"} group-hover:text-gcc-navy`}
                  >
                    {step.title}
                  </span>
                </button>
                {i < STEP_ORDER.length - 1 && (
                  <div className={`mt-3.5 h-0.5 flex-1 rounded-full ${stepLineClass[step.status]}`} />
                )}
              </div>
            );
          })}
        </div>

        {turn.expandedStep && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4 text-sm text-slate-700">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-gcc-navy/70">
                {turn.steps[turn.expandedStep].title}
              </p>
              <button
                type="button"
                onClick={() => onToggleStep(turn.id, { expandedStep: null })}
                className="text-xs text-slate-400 hover:text-slate-600"
              >
                {t("ask.hideReasoning")}
              </button>
            </div>
            {turn.steps[turn.expandedStep].error ? (
              <p className="text-red-600">{turn.steps[turn.expandedStep].error}</p>
            ) : turn.steps[turn.expandedStep].text ? (
              <Markdown text={turn.steps[turn.expandedStep].text} />
            ) : (
              <p className="text-slate-400">…</p>
            )}
          </div>
        )}

        {!turn.expandedStep && !turn.final && (turn.steps.intent_extraction.status !== "pending") && (
          <button
            type="button"
            onClick={() => toggle(turn.steps.final_synthesis.status !== "pending" ? "final_synthesis" : STEP_ORDER.find((s) => turn.steps[s].status === "active") ?? "intent_extraction")}
            className="mt-3 text-xs font-medium text-gcc-navy/70 hover:text-gcc-navy hover:underline"
          >
            {t("ask.showReasoning")}
          </button>
        )}

        {/* final answer */}
        {turn.final && (
          <div className="mt-5 rounded-xl border border-gcc-navy/15 bg-gradient-to-b from-gcc-sand/40 to-white p-4 sm:p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gcc-navy">
                <svg viewBox="0 0 20 20" fill="none" className="h-3.5 w-3.5">
                  <path
                    d="M10 2l1.9 4.6 5 .4-3.8 3.3 1.2 4.9L10 12.8 5.7 15.2l1.2-4.9L3.1 7l5-.4L10 2z"
                    fill="currentColor"
                  />
                </svg>
                {t("ask.answer")}
              </p>
              <div className="flex items-center gap-2">
                {turn.evalResult && (
                  <span className={turn.evalResult.all_verified ? "badge-ok" : "badge-warn"}>
                    {turn.evalResult.all_verified
                      ? t("ask.citationsVerified")
                      : `${turn.evalResult.unverified_rule_ids.length + turn.evalResult.unverified_gso_codes.length} ${t("ask.citationsUnverified")}`}
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
            <Markdown text={turn.final.answer} className="text-sm text-slate-800" />
            {exportError && <p className="mt-2 text-xs text-red-600">{exportError}</p>}
            {turn.evalResult && !turn.evalResult.all_verified && (
              <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                <p className="font-semibold">{t("ask.unverifiedWarning")}</p>
                {turn.evalResult.unverified_rule_ids.length > 0 && (
                  <p className="mt-1">
                    {t("ask.unverifiedRuleIds")}: {turn.evalResult.unverified_rule_ids.join(", ")}
                  </p>
                )}
                {turn.evalResult.unverified_gso_codes.length > 0 && (
                  <p className="mt-1">
                    {t("ask.unverifiedGsoCodes")}: {turn.evalResult.unverified_gso_codes.map((c) => `GSO ${c}`).join(", ")}
                  </p>
                )}
              </div>
            )}
            {turn.final.error && <p className="mt-2 text-sm text-red-600">{turn.final.error}</p>}
            {turn.retryCount > 0 && (
              <p className="mt-3 text-[11px] text-slate-400">
                {turn.retryCount} {t("ask.retriedNote")}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
