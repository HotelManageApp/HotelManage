import { setRequestLocale } from "next-intl/server";
import { AreaTabs } from "@/components/layout/AreaTabs";
import { OrderList } from "@/components/reception/OrderList";

export default async function ReceptionOrdersPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="reception" />
      <OrderList />
    </div>
  );
}
