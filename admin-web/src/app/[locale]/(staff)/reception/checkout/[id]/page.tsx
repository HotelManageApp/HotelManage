import { setRequestLocale } from "next-intl/server";
import { CheckoutDesk } from "@/components/checkout/CheckoutDesk";

export default async function CheckoutDeskPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);
  return <CheckoutDesk requestId={id} />;
}
