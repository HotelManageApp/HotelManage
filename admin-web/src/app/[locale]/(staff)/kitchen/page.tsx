import { setRequestLocale } from "next-intl/server";
import { OrderBoard } from "@/components/kitchen/OrderBoard";
import { AreaTabs } from "@/components/layout/AreaTabs";

export default async function KitchenPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="kitchen" />
      <OrderBoard />
    </div>
  );
}
