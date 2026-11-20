import { setRequestLocale } from "next-intl/server";
import { StayDetail } from "@/components/reception/StayDetail";

export default async function StayPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);
  return <StayDetail stayId={id} />;
}
