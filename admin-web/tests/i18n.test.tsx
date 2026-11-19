import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import en from "../messages/en.json";
import viMessages from "../messages/vi.json";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/health",
}));

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([key, value]) =>
    typeof value === "object" && value !== null
      ? keys(value, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("messages", () => {
  it("vi and en define exactly the same keys", () => {
    expect(keys(en).sort()).toEqual(keys(viMessages).sort());
  });
});

describe("LocaleSwitcher", () => {
  it("switches to English on the same page", async () => {
    render(
      <NextIntlClientProvider locale="vi" messages={viMessages}>
        <LocaleSwitcher />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("Ngôn ngữ")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByRole("combobox"), "en");

    expect(replace).toHaveBeenCalledWith("/health", { locale: "en" });
  });
});
