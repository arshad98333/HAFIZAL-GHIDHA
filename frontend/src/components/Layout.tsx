import { Link, NavLink, Outlet } from "react-router-dom";
import { useI18n } from "../i18n/context";

export function Layout() {
  const { t, lang, setLang, dir } = useI18n();
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `text-sm font-medium transition ${isActive ? "text-gcc-navy" : "text-slate-600 hover:text-gcc-navy"}`;

  return (
    <div className="min-h-screen" dir={dir}>
      <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gcc-navy text-sm font-bold text-white">
              GCC
            </span>
            <span className="hidden font-semibold text-gcc-navy sm:block">Cold-Chain AI</span>
          </Link>
          <nav className="flex flex-wrap items-center gap-4 sm:gap-6">
            <NavLink to="/" className={navClass} end>
              {t("nav.home")}
            </NavLink>
            <NavLink to="/simulation" className={navClass}>
              {t("nav.simulation")}
            </NavLink>
            <NavLink to="/ask" className={navClass}>
              {t("nav.ask")}
            </NavLink>
            <NavLink to="/liveops" className={navClass}>
              {t("nav.liveops")}
            </NavLink>
          </nav>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setLang("en")}
              className={`rounded px-2 py-1 text-xs font-semibold ${lang === "en" ? "bg-gcc-navy text-white" : "text-slate-500"}`}
            >
              EN
            </button>
            <button
              type="button"
              onClick={() => setLang("ar")}
              className={`rounded px-2 py-1 text-xs font-semibold ${lang === "ar" ? "bg-gcc-navy text-white" : "text-slate-500"}`}
            >
              عربي
            </button>
          </div>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
      <footer className="mt-16 border-t border-slate-200 bg-white py-8 text-center text-sm text-slate-500">
        GCC Cold-Chain Compliance AI · GSO-aligned · {t("landing.jurisdictions")}
      </footer>
    </div>
  );
}
