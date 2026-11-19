import { setRequestLocale } from "next-intl/server";
import { MenuTable } from "@/components/kitchen/MenuTable";
import { AreaTabs } from "@/components/layout/AreaTabs";

export default async function KitchenMenuPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="kitchen" />
      <MenuTable />
    </div>
  );
}
