import { setRequestLocale } from "next-intl/server";
import { HousekeepingBoard } from "@/components/housekeeping/HousekeepingBoard";

export default async function HousekeepingPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  setRequestLocale((await params).locale);
  return <HousekeepingBoard />;
}
