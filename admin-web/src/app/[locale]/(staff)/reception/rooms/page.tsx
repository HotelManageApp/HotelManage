import { setRequestLocale } from "next-intl/server";
import { RoomManager } from "@/components/reception/RoomManager";

export default async function RoomsPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <RoomManager />;
}
