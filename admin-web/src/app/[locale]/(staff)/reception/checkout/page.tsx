import { setRequestLocale } from "next-intl/server";
import { CheckoutQueue } from "@/components/checkout/CheckoutQueue";
import { AreaTabs } from "@/components/layout/AreaTabs";

export default async function CheckoutQueuePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="reception" />
      <CheckoutQueue />
    </div>
  );
}
