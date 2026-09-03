import { useState } from "react";
import { useI18n } from "../i18n/context";

/**
 * A collapsible "what is this page" panel written for a food-safety
 * compliance officer, not a developer: what the page is for, what to type
 * in, and what comes back out. Every page that a compliance officer will
 * actually use (Ask, Simulation, LiveOps) carries one of these so nobody
 * has to guess the tool's purpose from a UI alone.
 */
export function PageExplainer({
  whatKey,
  inputKey,
  outputKey,
}: {
  whatKey: string;
  inputKey: string;
  outputKey: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-5 overflow-hidden rounded-xl border border-gcc-navy/15 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gcc-navy">
          <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4 shrink-0">
            <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10 9v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="10" cy="6.5" r="0.9" fill="currentColor" />
          </svg>
          {t("explainer.toggle")}
        </span>
        <svg
          viewBox="0 0 20 20"
          fill="none"
          className={`h-4 w-4 shrink-0 text-gcc-navy/60 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M5 7.5L10 12.5L15 7.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="grid gap-4 border-t border-slate-100 bg-gcc-sand/30 px-4 py-4 sm:grid-cols-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-gcc-navy/70">{t("explainer.whatLabel")}</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-700" dir="auto">
              {t(whatKey)}
            </p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-gcc-navy/70">{t("explainer.inputLabel")}</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-700" dir="auto">
              {t(inputKey)}
            </p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-gcc-navy/70">{t("explainer.outputLabel")}</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-700" dir="auto">
              {t(outputKey)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
