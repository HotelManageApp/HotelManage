import { setRequestLocale } from "next-intl/server";
import { AreaTabs } from "@/components/layout/AreaTabs";
import { RoomServiceSettingsForm } from "@/components/reception/RoomServiceSettingsForm";

export default async function ReceptionSettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="reception" />
      <RoomServiceSettingsForm />
    </div>
  );
}
