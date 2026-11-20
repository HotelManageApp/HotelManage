import { setRequestLocale } from "next-intl/server";
import { ChangePasswordForm } from "@/components/auth/ChangePasswordForm";

export default async function AccountPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <ChangePasswordForm />;
}
