"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { roleHome } from "@/lib/auth/roles";

/** "/" sends signed-in staff to their area and everyone else to the login page. */
export function HomeRedirect() {
  const t = useTranslations("Staff");
  const { state } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (state.status === "authenticated") router.replace(roleHome(state.staff.role));
    if (state.status === "anonymous") router.replace("/login");
  }, [state, router]);

  return <p className="p-6 text-sm text-slate-500">{t("loading")}</p>;
}
