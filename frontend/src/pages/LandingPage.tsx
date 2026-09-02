import { usePageMeta } from "../hooks/usePageMeta";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n/context";

const values = ["value1", "value2", "value3", "value4"] as const;

export function LandingPage() {
  const { t } = useI18n();
  usePageMeta(t("landing.seoTitle"), t("landing.seoDesc"));

  return (
    <>
      <section className="relative overflow-hidden bg-gradient-to-br from-gcc-navy via-gcc-teal to-gcc-navy text-white">
        <div className="absolute inset-0 opacity-10 bg-[radial-gradient(circle_at_30%_20%,#C4A35A_0%,transparent_50%)]" />
        <div className="relative mx-auto max-w-6xl px-4 py-20 sm:py-28">
          <p className="mb-4 inline-flex rounded-full border border-white/20 bg-white/10 px-4 py-1 text-sm font-medium backdrop-blur">
            {t("landing.badge")}
          </p>
          <h1 className="max-w-3xl text-4xl font-bold leading-tight tracking-tight sm:text-5xl lg:text-6xl">
            {t("landing.title")}
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-white/85 sm:text-xl">{t("landing.subtitle")}</p>
          <div className="mt-10 flex flex-wrap gap-4">
            <Link to="/dashboard" className="btn-primary bg-white text-gcc-navy hover:bg-gcc-sand">
              {t("landing.ctaPrimary")}
            </Link>
            <Link to="/guide" className="btn-secondary border-white/30 bg-transparent text-white hover:bg-white/10">
              {t("landing.ctaGuide")}
            </Link>
          </div>
          <p className="mt-8 text-sm font-medium tracking-widest text-gcc-gold">{t("landing.jurisdictions")}</p>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16">
        <h2 className="text-center text-2xl font-bold text-gcc-navy sm:text-3xl">{t("landing.valueTitle")}</h2>
        <div className="mt-12 grid gap-6 sm:grid-cols-2">
          {values.map((v) => (
            <article key={v} className="card border-gcc-gold/20">
              <h3 className="text-lg font-semibold text-gcc-navy">{t(`landing.${v}Title`)}</h3>
              <p className="mt-2 text-slate-600 leading-relaxed">{t(`landing.${v}Body`)}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="bg-white py-16">
        <div className="mx-auto max-w-6xl px-4 text-center">
          <p className="text-sm uppercase tracking-wider text-slate-500">GSO · HACCP · SFDA · ESMA</p>
          <p className="mt-4 text-slate-600">
            Deterministic rules engine · Agentic Gate A/B · 12 KPI dimensions · MongoDB audit trail
          </p>
        </div>
      </section>
    </>
  );
}
