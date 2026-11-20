import { setRequestLocale } from "next-intl/server";
import { AreaTabs } from "@/components/layout/AreaTabs";
import { HousekeepingList } from "@/components/reception/HousekeepingList";

export default async function ReceptionHousekeepingPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="reception" />
      <HousekeepingList />
    </div>
  );
}
