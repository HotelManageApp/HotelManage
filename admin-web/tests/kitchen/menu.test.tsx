import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MenuTable } from "@/components/kitchen/MenuTable";
import type { MenuCategory, MenuItem, RoomServiceSettings } from "@/lib/menu/types";
import { json, mockBackend, renderWithAuth, session } from "../auth/helpers";

const COOK = { id: "k1", email: "bep@h.test", full_name: "Bep", role: "KITCHEN" as const };

const MAIN: MenuCategory = {
  id: "c-main",
  code: "MAIN",
  name_vi: "Món chính",
  name_en: "Mains",
  sort_order: 0,
  is_active: true,
};
const DRINK: MenuCategory = { ...MAIN, id: "c-drink", code: "DRINK", name_vi: "Đồ uống" };

function item(overrides: Partial<MenuItem> = {}): MenuItem {
  return {
    id: "i1",
    category_id: "c-main",
    name_vi: "Phở bò",
    name_en: "Beef pho",
    description_vi: null,
    description_en: null,
    price_vnd: 65000,
    available: true,
    is_archived: false,
    sort_order: 0,
    ...overrides,
  };
}

const SETTINGS: RoomServiceSettings = {
  room_service_open: "06:00:00",
  room_service_close: "22:00:00",
  room_service_paused: false,
  default_prep_minutes: 25,
};

type Fetch = ReturnType<typeof mockBackend>;

const callsTo = (fetchMock: Fetch, method: string, suffix: string) =>
  fetchMock.mock.calls
    .filter(([url, init]) => String(url).endsWith(suffix) && (init?.method ?? "GET") === method)
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));

function backend(routes: Record<string, () => Response> = {}, items = [item()]) {
  return mockBackend({
    "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, COOK)),
    "GET /api/v1/menu/categories": () => json([MAIN, DRINK]),
    "GET /api/v1/menu/items": () => json(items),
    "GET /api/v1/settings/room-service": () => json(SETTINGS),
    ...routes,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("MenuTable", () => {
  it("asks for archived dishes too and lists them apart", async () => {
    const fetchMock = backend({}, [
      item(),
      item({ id: "i2", name_vi: "Bún chả", is_archived: true }),
    ]);
    renderWithAuth(<MenuTable />);

    const row = await screen.findByTestId("item-i1");
    expect(row).toHaveTextContent("Phở bò");
    expect(row).toHaveTextContent("Món chính");
    expect(row).toHaveTextContent("65.000 ₫");
    expect(screen.queryByTestId("item-i2")).not.toBeInTheDocument();
    expect(screen.getByText("Món đã lưu trữ (1)")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).endsWith("/menu/items?include_archived=true")),
    ).toBe(true);
  });

  it("marks a dish sold out with the switch", async () => {
    const fetchMock = backend({
      "POST /api/v1/menu/items/i1/availability": () => json(item({ available: false })),
    });
    renderWithAuth(<MenuTable />);

    await userEvent.click(await screen.findByRole("switch", { name: "Còn món Phở bò" }));
    await waitFor(() =>
      expect(callsTo(fetchMock, "POST", "/menu/items/i1/availability")).toEqual([
        { available: false },
      ]),
    );
  });

  it("adds a dish only once the name and a whole-number price are filled in", async () => {
    const fetchMock = backend({ "POST /api/v1/menu/items": () => json(item(), 201) });
    renderWithAuth(<MenuTable />);

    const form = await screen.findByRole("form", { name: "Thêm món" });
    const submit = within(form).getByRole("button", { name: "Thêm món" });
    expect(submit).toBeDisabled();
    await userEvent.selectOptions(within(form).getByLabelText("Nhóm"), "c-drink");
    await userEvent.type(within(form).getByLabelText("Tên món"), "Cà phê sữa");
    await userEvent.type(within(form).getByLabelText("Giá (₫)"), "2.5");
    expect(submit).toBeDisabled();
    await userEvent.clear(within(form).getByLabelText("Giá (₫)"));
    await userEvent.type(within(form).getByLabelText("Giá (₫)"), "35000");
    await userEvent.click(submit);

    await waitFor(() =>
      expect(callsTo(fetchMock, "POST", "/api/v1/menu/items")).toEqual([
        {
          category_id: "c-drink",
          name_vi: "Cà phê sữa",
          name_en: "Cà phê sữa",
          description_vi: null,
          price_vnd: 35000,
        },
      ]),
    );
    await waitFor(() => expect(within(form).getByLabelText("Tên món")).toHaveValue(""));
  });

  it("edits a dish's price", async () => {
    const fetchMock = backend({ "PATCH /api/v1/menu/items/i1": () => json(item()) });
    renderWithAuth(<MenuTable />);

    await userEvent.click(await screen.findByRole("button", { name: "Sửa" }));
    const price = screen.getByLabelText("Phở bò: Giá (₫)");
    await userEvent.clear(price);
    await userEvent.type(price, "70000");
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() =>
      expect(callsTo(fetchMock, "PATCH", "/menu/items/i1")).toEqual([
        {
          category_id: "c-main",
          name_vi: "Phở bò",
          name_en: "Beef pho",
          description_vi: null,
          price_vnd: 70000,
        },
      ]),
    );
    await waitFor(() => expect(screen.queryByLabelText("Phở bò: Giá (₫)")).not.toBeInTheDocument());
  });

  it("archives and restores a dish", async () => {
    const fetchMock = backend(
      {
        "PATCH /api/v1/menu/items/i1": () => json(item()),
        "PATCH /api/v1/menu/items/i2": () => json(item()),
      },
      [item(), item({ id: "i2", name_vi: "Bún chả", is_archived: true })],
    );
    renderWithAuth(<MenuTable />);

    await userEvent.click(await screen.findByRole("button", { name: "Lưu trữ Phở bò" }));
    await userEvent.click(screen.getByText("Món đã lưu trữ (1)"));
    await userEvent.click(screen.getByRole("button", { name: "Khôi phục Bún chả" }));

    await waitFor(() =>
      expect(callsTo(fetchMock, "PATCH", "/menu/items/i2")).toEqual([{ is_archived: false }]),
    );
    expect(callsTo(fetchMock, "PATCH", "/menu/items/i1")).toEqual([{ is_archived: true }]);
  });

  it("pauses room service for the whole kitchen", async () => {
    const fetchMock = backend({
      "PATCH /api/v1/settings/room-service": () => json({ ...SETTINGS, room_service_paused: true }),
    });
    renderWithAuth(<MenuTable />);

    await userEvent.click(await screen.findByRole("button", { name: "Tạm ngưng nhận đơn" }));
    await waitFor(() =>
      expect(callsTo(fetchMock, "PATCH", "/settings/room-service")).toEqual([{ paused: true }]),
    );
  });

  it("explains when a change cannot be saved", async () => {
    backend({
      "POST /api/v1/menu/items/i1/availability": () =>
        json({ error: { code: "FORBIDDEN", message: "x", details: [], request_id: "r" } }, 403),
    });
    renderWithAuth(<MenuTable />);

    await userEvent.click(await screen.findByRole("switch", { name: "Còn món Phở bò" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không lưu được");
  });
});
