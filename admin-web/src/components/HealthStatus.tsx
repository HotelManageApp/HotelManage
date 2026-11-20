import { useTranslations } from "next-intl";
import type { HealthResult } from "@/lib/health";

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-sm font-medium ${
        ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"
      }`}
    >
      {label}
    </span>
  );
}

export function HealthStatus({ result }: { result: HealthResult }) {
  const t = useTranslations("Health");

  if (!result.reachable) {
    return (
      <p role="alert" className="rounded bg-red-50 p-4 text-red-800">
        {t("unreachable")}
      </p>
    );
  }

  const { health } = result;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-3">
      <dt>{t("backend")}</dt>
      <dd>
        <Badge ok={health.status === "ok"} label={health.status === "ok" ? t("ok") : t("error")} />
      </dd>
      <dt>{t("database")}</dt>
      <dd>
        <Badge ok={health.db === "ok"} label={health.db === "ok" ? t("ok") : t("error")} />
      </dd>
      <dt>{t("version")}</dt>
      <dd className="font-mono text-sm">{health.version}</dd>
    </dl>
  );
}
