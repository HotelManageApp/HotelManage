import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrderBoard } from "@/components/kitchen/OrderBoard";
import type { StaffOrder } from "@/lib/orders/types";
import { envelope, json, mockBackend, session } from "../auth/helpers";
import { renderStaffScreen, sseRoute } from "../realtime/sse";

const COOK = { id: "k1", email: "bep@h.test", full_name: "Bep", role: "KITCHEN" as const };

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
        note: "ít cay",
      },
    ],
    total_vnd: 130000,
    order_note: "Gõ cửa nhẹ",
    source: "APP",
    estimated_minutes: null,
    cancel_reason: null,
    created_at: new Date(Date.now() - 3 * 60000).toISOString(),
    updated_at: new Date().toISOString(),
    version: 0,
    room_number: "101",
    guest_name: null,
    overdue: false,
    ...overrides,
  };
}

const bodyOf = (fetchMock: ReturnType<typeof mockBackend>, suffix: string) => {
  const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith(suffix));
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
};

afterEach(() => vi.unstubAllGlobals());

describe("OrderBoard", () => {
  it("puts orders in their columns with dishes, notes and waiting time", async () => {
    const sse = sseRoute();
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, COOK)),
      "GET /api/v1/staff/events": sse.handler,
      "GET /api/v1/orders": () =>
        json([
          order(),
          order({ id: "o2", status: "PREPARING", room_number: "202", version: 2, overdue: false }),
          order({ id: "o3", status: "PENDING", room_number: "303", overdue: true }),
          order({ id: "o4", status: "COMPLETED", room_number: "404" }),
        ]),
    });
    renderStaffScreen(<OrderBoard />);

    const pending = await screen.findByRole("region", { name: "Chờ nhận" });
    const card = within(pending).getByTestId("order-101");
    expect(card).toHaveTextContent("2 ×");
    expect(card).toHaveTextContent("Phở bò");
    expect(card).toHaveTextContent("ít cay");
    expect(card).toHaveTextContent("Gõ cửa nhẹ");
    expect(card).toHaveTextContent("3 phút trước");
    expect(within(pending).getByTestId("order-303").className).toContain("border-red-600");
    expect(
      within(screen.getByRole("region", { name: "Đang nấu" })).getByTestId("order-202"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Đã xong \/ đã hủy gần đây \(1\)/)).toBeInTheDocument();
  });

  it("accepts an order with an estimate and moves the next one on", async () => {
    const sse = sseRoute();
    // The board loads on mount and again when the event stream opens, so the list only
    // changes once the kitchen has actually accepted the order.
    let accepted = false;
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, COOK)),
      "GET /api/v1/staff/events": sse.handler,
      "GET /api/v1/orders": () =>
        accepted
          ? json([order({ status: "CONFIRMED", version: 1 })])
          : json([
              order(),
              order({ id: "o2", status: "PREPARING", room_number: "202", version: 2 }),
            ]),
      "POST /api/v1/orders/o1/transition": () => {
        accepted = true;
        return json(order({ status: "CONFIRMED", version: 1 }));
      },
      "POST /api/v1/orders/o2/transition": () => json(order({ id: "o2", status: "DELIVERING" })),
    });
    renderStaffScreen(<OrderBoard />);

    await userEvent.click(await screen.findByRole("button", { name: "Mang đi giao" }));
    await waitFor(() =>
      expect(bodyOf(fetchMock, "/orders/o2/transition")).toEqual({ to: "DELIVERING", version: 2 }),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Nhận · 25′" }));
    await waitFor(() =>
      expect(bodyOf(fetchMock, "/orders/o1/transition")).toEqual({
        to: "CONFIRMED",
        version: 0,
        estimated_minutes: 25,
      }),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("region", { name: "Đã nhận" })).getByTestId("order-101"),
      ).toBeInTheDocument(),
    );
  });

  it("rejecting needs a reason", async () => {
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, COOK)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/orders": () => json([order()]),
      "POST /api/v1/orders/o1/cancel": () => json(order({ status: "CANCELLED" })),
    });
    renderStaffScreen(<OrderBoard />);
    await userEvent.click(await screen.findByRole("button", { name: "Từ chối đơn" }));
    const submit = screen.getByRole("button", { name: "Từ chối" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Lý do từ chối (khách sẽ thấy)"), "Hết phở");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(bodyOf(fetchMock, "/orders/o1/cancel")).toEqual({ version: 0, reason: "Hết phở" }),
    );
  });

  it("explains a stale order and reloads", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, COOK)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/orders": () => json([order({ status: "CONFIRMED", version: 1 })]),
      "POST /api/v1/orders/o1/transition": () => envelope(409, "CONFLICT"),
    });
    renderStaffScreen(<OrderBoard />);
    await userEvent.click(await screen.findByRole("button", { name: "Bắt đầu nấu" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("vừa được người khác cập nhật");
  });

  it("reloads when a food-order event arrives", async () => {
    const sse = sseRoute();
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, COOK)),
      "GET /api/v1/staff/events": sse.handler,
      "GET /api/v1/orders": [() => json([]), () => json([]), () => json([order()])],
    });
    renderStaffScreen(<OrderBoard />);
    await screen.findByRole("region", { name: "Chờ nhận" });
    const before = fetchMock.mock.calls.filter(([u]) =>
      String(u).endsWith("/api/v1/orders"),
    ).length;
    act(() => sse.push({ entity_type: "FOOD_ORDER", status: "PENDING", room_number: "101" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/v1/orders")).length,
      ).toBeGreaterThan(before),
    );
    act(() => sse.push({ entity_type: "HOUSEKEEPING", status: "REQUESTED", room_number: "101" }));
  });
});
