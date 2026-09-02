import { useEffect, useState } from "react";
import { usePageMeta } from "../hooks/usePageMeta";
import { api, type Job } from "../api/client";
import { useI18n } from "../i18n/context";

export function JobsPage() {
  const { t } = useI18n();
  usePageMeta(`${t("jobs.title")} | GCC Cold-Chain AI`);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .jobs()
      .then(setJobs)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));
    const id = setInterval(() => {
      api.jobs().then(setJobs).catch(() => {});
    }, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
        <h1 className="text-3xl font-bold text-gcc-navy">{t("jobs.title")}</h1>
        {error && <p className="mt-4 text-red-600">{error}</p>}
        {jobs.length === 0 ? (
          <p className="mt-8 text-slate-500">{t("jobs.empty")}</p>
        ) : (
          <div className="mt-8 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-start text-slate-500">
                  <th className="py-2">{t("jobs.name")}</th>
                  <th>{t("jobs.wave")}</th>
                  <th>{t("jobs.status")}</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id} className="border-b border-slate-100">
                    <td className="py-3 font-medium">{j.name}</td>
                    <td>{j.wave ?? "—"}</td>
                    <td>
                      <span
                        className={
                          j.status === "succeeded"
                            ? "badge-ok"
                            : j.status === "failed"
                              ? "badge-fail"
                              : "badge-warn"
                        }
                      >
                        {j.status}
                      </span>
                    </td>
                    <td className="font-mono text-xs">{j.job_id.slice(0, 8)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
  );
}
