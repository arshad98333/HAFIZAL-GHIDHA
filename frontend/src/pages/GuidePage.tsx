import { usePageMeta } from "../hooks/usePageMeta";
import { api } from "../api/client";
import { useI18n } from "../i18n/context";

type CmdBlock = { titleKey: string; win: string; unix: string };

const commands: CmdBlock[] = [
  {
    titleKey: "guide.goalUpdateAll",
    win: ".\\scripts\\update-all.ps1",
    unix: "make update-all",
  },
  {
    titleKey: "guide.goalRescore",
    win: ".\\scripts\\run.ps1",
    unix: "make run",
  },
  {
    titleKey: "guide.goalSmoke",
    win: ".\\scripts\\run.ps1 -Profile smoke",
    unix: "make run-smoke",
  },
  {
    titleKey: "guide.goalWave",
    win: ".\\scripts\\run.ps1 -Profile wave",
    unix: "make run-wave",
  },
  {
    titleKey: "guide.goalApi",
    win: ".\\scripts\\api_server.ps1",
    unix: "make api",
  },
  {
    titleKey: "guide.goalUi",
    win: "cd frontend; npm install; npm run dev",
    unix: "cd frontend && npm install && npm run dev",
  },
  {
    titleKey: "guide.goalSync",
    win: ".\\scripts\\watch-sync-desktop.ps1",
    unix: "./scripts/sync-desktop-folder.ps1",
  },
];

function Code({ children }: { children: string }) {
  return (
    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-4 text-sm text-emerald-300">
      <code>{children}</code>
    </pre>
  );
}

export function GuidePage() {
  const { t } = useI18n();
  usePageMeta(`${t("guide.title")} | GCC Cold-Chain AI`);

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-bold text-gcc-navy">{t("guide.title")}</h1>
        <p className="mt-2 text-slate-600">{t("guide.subtitle")}</p>

        <div className="card mt-8">
          <h2 className="font-semibold">{t("guide.prereq")}</h2>
          <p className="mt-2 text-slate-600">{t("guide.prereqList")}</p>
        </div>

        <p className="mt-4 text-sm text-slate-500">
          {t("guide.backendLink")}: <code className="rounded bg-slate-100 px-1">{api.baseUrl}</code>
        </p>

        <h2 className="mt-10 text-xl font-semibold text-gcc-navy">{t("guide.goals")}</h2>
        <div className="mt-6 space-y-8">
          {commands.map((c) => (
            <section key={c.titleKey}>
              <h3 className="font-medium text-gcc-teal">{t(c.titleKey)}</h3>
              <p className="mt-1 text-xs font-semibold uppercase text-slate-400">{t("guide.windows")}</p>
              <Code>{c.win}</Code>
              <p className="mt-3 text-xs font-semibold uppercase text-slate-400">{t("guide.linux")}</p>
              <Code>{c.unix}</Code>
            </section>
          ))}
        </div>

        <div className="card mt-10 border-amber-200 bg-amber-50/50">
          <h2 className="font-semibold text-amber-900">{t("guide.troubleshoot")}</h2>
          <ul className="mt-3 list-disc space-y-2 ps-5 text-sm text-amber-950">
            <li>{t("guide.t1")}</li>
            <li>{t("guide.t2")}</li>
            <li>{t("guide.t3")}</li>
          </ul>
        </div>
      </div>
  );
}
