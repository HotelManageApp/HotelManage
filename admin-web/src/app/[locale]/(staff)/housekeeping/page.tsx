import { setRequestLocale } from "next-intl/server";
import { AreaHome } from "@/components/auth/AreaHome";

export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <AreaHome area="housekeeping" />;
}
