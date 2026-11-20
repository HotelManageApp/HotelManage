import { setRequestLocale } from "next-intl/server";
import { StayBill } from "@/components/checkout/StayBill";

export default async function StayBillPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);
  return <StayBill stayId={id} />;
}
