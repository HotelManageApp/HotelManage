import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrderList } from "@/components/reception/OrderList";
import { RoomServiceSettingsForm } from "@/components/reception/RoomServiceSettingsForm";
import type { StaffOrder } from "@/lib/orders/types";
import { envelope, json, mockBackend, renderWithAuth, session } from "../auth/helpers";
import { renderStaffScreen, sseRoute } from "../realtime/sse";

const search = vi.hoisted(() => ({ value: "" }));
vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useSearchParams: () => new URLSearchParams(search.value),
}));

const RECEPTIONIST = {
  id: "r-1",
  email: "le.tan@hotel.test",
  full_name: "Le Tan",
  role: "RECEPTION" as const,
};
const signedIn = { "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)) };

function order(overrides: Partial<StaffOrder> = {}): StaffOrder {
  return {
    id: "o1",
    status: "PENDING",
    items: [
      {
        item_id: "i1",
        name: "Phở bò",
        quantity: 2,
        unit_price_vnd: 65000,
        line_total_vnd: 130000,
        note: null,
      },
    ],
    total_vnd: 130000,
    order_note: null,
    source: "APP",
    estimated_minutes: null,
    cancel_reason: null,
    created_at: new Date(Date.now() - 12 * 60000).toISOString(),
    updated_at: new Date().toISOString(),
    version: 0,
    room_number: "101",
    guest_name: "Tran Thi B",
    overdue: false,
    history: null,
    ...overrides,
  };
}

type Fetch = ReturnType<typeof mockBackend>;
const urls = (fetchMock: Fetch, path: string) =>
  fetchMock.mock.calls
    .map(([u]) => new URL(String(u)))
    .filter((u) => u.pathname === path)
    .map((u) => u.search);
const bodyOf = (fetchMock: Fetch, suffix: string) => {
  const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith(suffix));
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
};

afterEach(() => {
  vi.unstubAllGlobals();
  search.value = "";
});

describe("OrderList", () => {
  it("lists orders with guest, total and overdue, and filters by status and room", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/orders": () =>
        json([order(), order({ id: "o2", room_number: "202", overdue: true, guest_name: null })]),
    });
    renderStaffScreen(<OrderList />);

    const row = await screen.findByTestId("order-row-o1");
    expect(row).toHaveTextContent("Tran Thi B");
    expect(row).toHaveTextContent("2× Phở bò");
    expect(row).toHaveTextContent("130.000 ₫");
    expect(row).toHaveTextContent("12 phút trước");
    expect(screen.getByTestId("order-row-o2")).toHaveTextContent("quá hạn");

    await userEvent.selectOptions(screen.getByLabelText("Trạng thái"), "PENDING");
    await userEvent.type(screen.getByLabelText("Phòng"), "101");
    await waitFor(() =>
      expect(urls(fetchMock, "/api/v1/orders")).toContain("?status=PENDING&room=101"),
    );
    expect(urls(fetchMock, "/api/v1/orders")[0]).toBe("");
  });

  it("starts filtered by the room in the address (link from the checkout desk)", async () => {
    search.value = "room=101";
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/orders": () => json([order()]),
    });
    renderStaffScreen(<OrderList />);
    expect(await screen.findByLabelText("Phòng")).toHaveValue("101");
    await screen.findByTestId("order-row-o1");
    expect(urls(fetchMock, "/api/v1/orders")[0]).toBe("?room=101");
  });

  it("shows details with history and cancels with a reason", async () => {
    const detailed = order({
      order_note: "Gõ cửa nhẹ",
      history: [
        {
          from_status: null,
          to_status: "PENDING",
          at: order().created_at,
          by: "GUEST",
          reason: null,
        },
      ],
    });
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/orders": () => json([order()]),
      "GET /api/v1/orders/o1": () => json(detailed),
      "POST /api/v1/orders/o1/cancel": () =>
        json(order({ status: "CANCELLED", cancel_reason: "Khách đổi ý", version: 1 })),
    });
    renderStaffScreen(<OrderList />);

    await userEvent.click(await screen.findByRole("button", { name: "Xem đơn phòng 101" }));
    const detail = await screen.findByRole("complementary", { name: "Đơn phòng 101" });
    expect(detail).toHaveTextContent("Gõ cửa nhẹ");
    expect(detail).toHaveTextContent("Chờ nhận");

    const submit = within(detail).getByRole("button", { name: "Hủy đơn" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(detail).getByLabelText("Lý do hủy (khách sẽ thấy)"), "Khách đổi ý");
    await userEvent.click(submit);

    await waitFor(() =>
      expect(bodyOf(fetchMock, "/orders/o1/cancel")).toEqual({ version: 0, reason: "Khách đổi ý" }),
    );
    await waitFor(() => expect(detail).toHaveTextContent("Đã hủy · Khách đổi ý"));
    expect(within(detail).queryByRole("button", { name: "Hủy đơn" })).not.toBeInTheDocument();
  });

  it("does not offer cancelling once the kitchen is cooking", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/orders": () => json([order({ status: "PREPARING", version: 2 })]),
      "GET /api/v1/orders/o1": () => json(order({ status: "PREPARING", version: 2 })),
    });
    renderStaffScreen(<OrderList />);

    await userEvent.click(await screen.findByRole("button", { name: "Xem đơn phòng 101" }));
    const detail = await screen.findByRole("complementary", { name: "Đơn phòng 101" });
    expect(detail).toHaveTextContent("Đang nấu");
    expect(within(detail).queryByRole("button", { name: "Hủy đơn" })).not.toBeInTheDocument();
  });

  it("explains a stale order when cancelling conflicts", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/orders": () => json([order()]),
      "GET /api/v1/orders/o1": () => json(order()),
      "POST /api/v1/orders/o1/cancel": () => envelope(409, "CONFLICT"),
    });
    renderStaffScreen(<OrderList />);

    await userEvent.click(await screen.findByRole("button", { name: "Xem đơn phòng 101" }));
    await userEvent.type(await screen.findByLabelText("Lý do hủy (khách sẽ thấy)"), "Hết món");
    await userEvent.click(screen.getByRole("button", { name: "Hủy đơn" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Đơn vừa được cập nhật");
  });

  it("reloads the list and the open order when a food-order event arrives", async () => {
    const sse = sseRoute();
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/staff/events": sse.handler,
      "GET /api/v1/orders": () => json([order()]),
      "GET /api/v1/orders/o1": () => json(order()),
    });
    renderStaffScreen(<OrderList />);
    await userEvent.click(await screen.findByRole("button", { name: "Xem đơn phòng 101" }));
    await screen.findByRole("complementary", { name: "Đơn phòng 101" });
    const lists = urls(fetchMock, "/api/v1/orders").length;
    const details = urls(fetchMock, "/api/v1/orders/o1").length;

    act(() =>
      sse.push({
        entity_type: "FOOD_ORDER",
        entity_id: "o1",
        status: "CONFIRMED",
        room_number: "101",
      }),
    );
    await waitFor(() => {
      expect(urls(fetchMock, "/api/v1/orders").length).toBeGreaterThan(lists);
      expect(urls(fetchMock, "/api/v1/orders/o1").length).toBeGreaterThan(details);
    });
  });
});

describe("RoomServiceSettingsForm", () => {
  const SETTINGS = {
    room_service_open: "06:00:00",
    room_service_close: "22:00:00",
    room_service_paused: true,
    default_prep_minutes: 25,
  };

  it("shows the current hours and saves new ones", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/settings/room-service": () => json(SETTINGS),
      "PATCH /api/v1/settings/room-service/hours": () =>
        json({ ...SETTINGS, room_service_open: "18:00:00", room_service_close: "02:00:00" }),
    });
    renderWithAuth(<RoomServiceSettingsForm />);

    const opens = await screen.findByLabelText("Mở cửa");
    expect(opens).toHaveValue("06:00");
    expect(screen.getByText("Bếp đang tạm ngưng nhận đơn")).toBeInTheDocument();
    await userEvent.clear(opens);
    await userEvent.type(opens, "18:00");
    const closes = screen.getByLabelText("Đóng cửa");
    await userEvent.clear(closes);
    await userEvent.type(closes, "02:00");
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() =>
      expect(bodyOf(fetchMock, "/settings/room-service/hours")).toEqual({
        open: "18:00",
        close: "02:00",
        default_prep_minutes: 25,
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu giờ phục vụ");
  });

  it("blocks a preparation time out of range and reports a refused save", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/settings/room-service": () => json(SETTINGS),
      "PATCH /api/v1/settings/room-service/hours": () => envelope(400, "VALIDATION_ERROR"),
    });
    renderWithAuth(<RoomServiceSettingsForm />);

    const prep = await screen.findByLabelText("Thời gian chuẩn bị mặc định (phút)");
    await userEvent.clear(prep);
    await userEvent.type(prep, "3");
    expect(screen.getByRole("button", { name: "Lưu" })).toBeDisabled();
    await userEvent.type(prep, "0");
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Giờ phục vụ chưa hợp lệ");
  });
});
