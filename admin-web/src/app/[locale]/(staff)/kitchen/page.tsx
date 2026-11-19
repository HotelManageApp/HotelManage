import { setRequestLocale } from "next-intl/server";
import { OrderBoard } from "@/components/kitchen/OrderBoard";

export default async function KitchenPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <OrderBoard />;
}
