"use client";

import { useTranslations } from "next-intl";
import { useEffect, type ReactNode } from "react";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { canAccess, roleHome } from "@/lib/auth/roles";

/**
 * Client-side gate for staff pages: sends anonymous users to /login and shows a 403 screen for
 * another role's area. This is UX only — every API call is authorised again by the backend.
 */
export function StaffGuard({ children }: { children: ReactNode }) {
  const t = useTranslations("Staff");
  const { state } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (state.status === "anonymous") router.replace("/login");
  }, [state.status, router]);

  if (state.status !== "authenticated") {
    return <p className="p-6 text-sm text-slate-500">{t("loading")}</p>;
  }
  if (!canAccess(state.staff.role, pathname)) {
    return (
      <section role="alert" className="space-y-3 p-6">
        <h1 className="text-xl font-semibold">{t("forbiddenTitle")}</h1>
        <p>{t("forbiddenBody")}</p>
        <Link href={roleHome(state.staff.role)} className="text-teal-700 underline">
          {t("backToMyArea")}
        </Link>
      </section>
    );
  }
  return <>{children}</>;
}
