import { setRequestLocale } from "next-intl/server";
import { AreaTabs } from "@/components/layout/AreaTabs";
import { HotelInfoForm } from "@/components/reception/HotelInfoForm";
import { RoomServiceSettingsForm } from "@/components/reception/RoomServiceSettingsForm";

export default async function ReceptionSettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-8">
      <AreaTabs area="reception" />
      <HotelInfoForm />
      <RoomServiceSettingsForm />
    </div>
  );
}
