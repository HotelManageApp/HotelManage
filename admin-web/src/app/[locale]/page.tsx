import { setRequestLocale } from "next-intl/server";
import { HomeRedirect } from "@/components/auth/HomeRedirect";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <HomeRedirect />;
}
