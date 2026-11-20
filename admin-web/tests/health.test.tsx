import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HealthStatus } from "@/components/HealthStatus";
import { getBackendHealth, type HealthResult } from "@/lib/health";
import en from "../messages/en.json";
import viMessages from "../messages/vi.json";

function renderIn(locale: "vi" | "en", result: HealthResult) {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "vi" ? viMessages : en}>
      <HealthStatus result={result} />
    </NextIntlClientProvider>,
  );
}

const healthy: HealthResult = {
  reachable: true,
  health: { status: "ok", db: "ok", version: "abc123" },
};

afterEach(() => vi.unstubAllGlobals());

describe("HealthStatus", () => {
  it("shows status in Vietnamese", () => {
    renderIn("vi", healthy);
    expect(screen.getByText("Cơ sở dữ liệu")).toBeInTheDocument();
    expect(screen.getAllByText("Hoạt động")).toHaveLength(2);
    expect(screen.getByText("abc123")).toBeInTheDocument();
  });

  it("shows status in English", () => {
    renderIn("en", healthy);
    expect(screen.getByText("Database")).toBeInTheDocument();
    expect(screen.getAllByText("Operational")).toHaveLength(2);
  });

  it("shows a database error", () => {
    renderIn("en", { reachable: true, health: { status: "degraded", db: "error", version: "x" } });
    expect(screen.getAllByText("Error")).toHaveLength(2);
  });

  it("shows an alert when the backend is unreachable", () => {
    renderIn("vi", { reachable: false });
    expect(screen.getByRole("alert")).toHaveTextContent("Không kết nối được tới máy chủ");
  });
});

describe("getBackendHealth", () => {
  it("returns the health body on 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ status: "ok", db: "ok", version: "v1" })),
    );
    expect(await getBackendHealth("http://b")).toEqual({
      reachable: true,
      health: { status: "ok", db: "ok", version: "v1" },
    });
  });

  it("treats 503 with a health body as reachable but degraded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ status: "degraded", db: "error", version: "v1" }, { status: 503 }),
      ),
    );
    expect(await getBackendHealth("http://b")).toEqual({
      reachable: true,
      health: { status: "degraded", db: "error", version: "v1" },
    });
  });

  it("returns unreachable on network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    expect(await getBackendHealth("http://b")).toEqual({ reachable: false });
  });
});
