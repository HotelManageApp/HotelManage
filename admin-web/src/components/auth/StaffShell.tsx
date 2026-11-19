"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { RealtimeBar } from "@/components/layout/RealtimeBar";
import { Link, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { roleHome } from "@/lib/auth/roles";

/** Bar under the app header: who is signed in, their area, account and sign-out. */
export function StaffShell({ children }: { children: ReactNode }) {
  const t = useTranslations("Staff");
  const tRole = useTranslations("Roles");
  const { state, logout } = useAuth();
  const router = useRouter();

  if (state.status !== "authenticated") return <>{children}</>;
  const { staff } = state;

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className="space-y-6">
      <nav className="flex flex-wrap items-center gap-4 rounded border border-slate-200 bg-white px-4 py-2 text-sm">
        <Link href={roleHome(staff.role)} className="font-medium text-teal-800">
          {tRole(staff.role)}
        </Link>
        <span className="text-slate-500" data-testid="staff-name">
          {staff.full_name}
        </span>
        <span className="ml-auto flex items-center gap-4">
          <RealtimeBar />
          <Link href="/account" className="underline">
            {t("account")}
          </Link>
          <button type="button" onClick={onLogout} className="underline">
            {t("logout")}
          </button>
        </span>
      </nav>
      {children}
    </div>
  );
}
