import { setRequestLocale } from "next-intl/server";
import { RoomBoard } from "@/components/reception/RoomBoard";

export default async function ReceptionPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <RoomBoard />;
}
