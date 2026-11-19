import { useTranslations } from "next-intl";
import type { Area } from "@/lib/auth/roles";

/** Empty landing page of a role area; each module adds its real screen here later. */
export function AreaHome({ area }: { area: Area }) {
  const t = useTranslations("Areas");
  return (
    <section className="space-y-2">
      <h1 className="text-xl font-semibold">{t(`${area}.title`)}</h1>
      <p className="rounded border border-dashed border-slate-300 p-6 text-center text-slate-500">
        {t("empty")}
      </p>
    </section>
  );
}
