"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import type { Area } from "@/lib/auth/roles";

const TABS: Record<Area, { href: string; key: string }[]> = {
  reception: [
    { href: "/reception", key: "rooms" },
    { href: "/reception/orders", key: "orders" },
    { href: "/reception/housekeeping", key: "housekeeping" },
    { href: "/reception/knowledge", key: "knowledge" },
    { href: "/reception/settings", key: "settings" },
  ],
  kitchen: [
    { href: "/kitchen", key: "queue" },
    { href: "/kitchen/menu", key: "menu" },
  ],
  housekeeping: [{ href: "/housekeeping", key: "queue" }],
};

/** Sub-navigation inside a role area. */
export function AreaTabs({ area }: { area: Area }) {
  const t = useTranslations("AreaTabs");
  const pathname = usePathname();
  return (
    <nav aria-label={t("label")} className="flex gap-4 border-b border-slate-200 text-sm">
      {TABS[area].map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`-mb-px border-b-2 px-1 pb-2 ${
              active ? "border-teal-700 font-medium text-teal-800" : "border-transparent"
            }`}
          >
            {t(`${area}.${tab.key}`)}
          </Link>
        );
      })}
    </nav>
  );
}
