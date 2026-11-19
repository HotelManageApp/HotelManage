import { setRequestLocale } from "next-intl/server";
import { AreaTabs } from "@/components/layout/AreaTabs";
import { RoomBoard } from "@/components/reception/RoomBoard";

export default async function ReceptionPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="reception" />
      <RoomBoard />
    </div>
  );
}
