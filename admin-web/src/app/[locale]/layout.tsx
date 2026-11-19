import type { Metadata } from "next";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import { routing } from "@/i18n/routing";
import "../globals.css";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "App" });
  return { title: t("title") };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations("App");

  return (
    <html lang={locale}>
      <body className="min-h-screen">
        <NextIntlClientProvider>
          <AuthProvider>
            <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
              <div>
                <p className="font-semibold">{t("title")}</p>
                <p className="text-xs text-slate-500">{t("tagline")}</p>
              </div>
              <LocaleSwitcher />
            </header>
            <main className="mx-auto max-w-5xl p-6">{children}</main>
          </AuthProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
