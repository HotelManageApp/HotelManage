import { getTranslations, setRequestLocale } from "next-intl/server";
import { HealthStatus } from "@/components/HealthStatus";
import { Link } from "@/i18n/navigation";
import { getBackendHealth } from "@/lib/health";
import { backendUrl } from "@/lib/server-config";

// Always fetch live status; never prerender this page.
export const dynamic = "force-dynamic";

export default async function HealthPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Health");
  const result = await getBackendHealth(backendUrl());

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <HealthStatus result={result} />
      <Link href="/" className="text-sm text-blue-700 underline">
        {t("back")}
      </Link>
    </section>
  );
}
