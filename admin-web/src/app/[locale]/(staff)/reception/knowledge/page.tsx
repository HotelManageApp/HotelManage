import { setRequestLocale } from "next-intl/server";
import { KnowledgeManager } from "@/components/knowledge/KnowledgeManager";
import { AreaTabs } from "@/components/layout/AreaTabs";

export default async function ReceptionKnowledgePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  setRequestLocale((await params).locale);
  return (
    <div className="space-y-4">
      <AreaTabs area="reception" />
      <KnowledgeManager />
    </div>
  );
}
