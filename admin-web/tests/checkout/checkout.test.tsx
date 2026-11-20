import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CheckoutDesk } from "@/components/checkout/CheckoutDesk";
import { CheckoutQueue } from "@/components/checkout/CheckoutQueue";
import { StayBill } from "@/components/checkout/StayBill";
import type { Bill, CheckoutDetail, CheckoutRequest } from "@/lib/checkout/types";
import { envelope, json, mockBackend, renderWithAuth, session } from "../auth/helpers";
import { renderStaffScreen, sseRoute } from "../realtime/sse";

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/reception/checkout",
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const RECEPTIONIST = {
  id: "r-1",
  email: "lt@h.test",
  full_name: "Le Tan",
  role: "RECEPTION" as const,
};
const signedIn = {
  "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)),
  "GET /api/v1/staff/events": sseRoute().handler,
  "GET /api/v1/settings/hotel": () => json({ hotel_name: "Khách sạn Hoa Sen" }),
};

const BILL: Bill = {
  stay: {
    room_number: "101",
    guest_name: "Tran Thi B",
    checkin_at: "2026-11-19T07:00:00Z",
    expected_checkout_at: "2026-11-21T05:00:00Z",
  },
  lines: [
    {
      type: "ROOM",
      description: "Tiền phòng",
      amount_vnd: 1_200_000,
      order_id: null,
      charge_id: null,
    },
    {
      type: "FOOD",
      description: "Đơn #A1B2 (2 món)",
      amount_vnd: 130_000,
      order_id: "o1",
      charge_id: null,
    },
    { type: "EXTRA", description: "Minibar", amount_vnd: 60_000, order_id: null, charge_id: "c1" },
    {
      type: "DISCOUNT",
      description: "Khách quen",
      amount_vnd: 50_000,
      order_id: null,
      charge_id: "c2",
    },
  ],
  total_vnd: 1_340_000,
  open_orders: 0,
  currency: "VND",
  generated_at: "2026-11-20T03:00:00Z",
};

function request(overrides: Partial<CheckoutRequest> = {}): CheckoutRequest {
  return {
    id: "q1",
    stay_id: "s1",
    room_number: "101",
    guest_name: "Tran Thi B",
    status: "CHECKOUT_REQUESTED",
    source: "APP",
    feedback_rating: 4,
    feedback_note: null,
    total_vnd: null,
    payment_method: null,
    reject_reason: null,
    created_at: new Date(Date.now() - 4 * 60000).toISOString(),
    verified_at: null,
    completed_at: null,
    rejected_at: null,
    version: 0,
    overdue: false,
    open_orders: 0,
    ...overrides,
  };
}

function detail(overrides: Partial<CheckoutDetail> = {}): CheckoutDetail {
  return {
    ...request(),
    bill: BILL,
    bill_is_snapshot: false,
    open_order_ids: [],
    history: [],
    feedback_note: "Phòng sạch sẽ",
    ...overrides,
  };
}

type Fetch = ReturnType<typeof mockBackend>;
const calls = (fetchMock: Fetch, method: string, path: string) =>
  fetchMock.mock.calls
    .filter(
      ([u, init]) => new URL(String(u)).pathname === path && (init?.method ?? "GET") === method,
    )
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : undefined));

let print: ReturnType<typeof vi.fn>;
beforeEach(() => {
  print = vi.fn();
  vi.stubGlobal("print", print);
});
afterEach(() => vi.unstubAllGlobals());

describe("CheckoutQueue", () => {
  it("shows open requests with warnings and finished ones apart", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/checkout-requests": () =>
        json([
          request(),
          request({
            id: "q2",
            room_number: "202",
            open_orders: 2,
            overdue: true,
            feedback_rating: null,
          }),
          request({ id: "q3", room_number: "303", status: "COMPLETED", total_vnd: 900_000 }),
        ]),
    });
    renderStaffScreen(<CheckoutQueue />);

    const first = await screen.findByTestId("checkout-q1");
    expect(first).toHaveAttribute("href", "/reception/checkout/q1");
    expect(first).toHaveTextContent("Phòng 101");
    expect(first).toHaveTextContent("Chờ đối soát");
    expect(first).toHaveTextContent("gửi 4 phút trước");
    expect(first).toHaveTextContent("★★★★");
    const second = screen.getByTestId("checkout-q2");
    expect(second).toHaveTextContent("2 đơn đồ ăn chưa giao xong");
    expect(second.className).toContain("border-red-600");
    expect(screen.getByText("Đã xử lý trong 24 giờ qua (1)")).toBeInTheDocument();
  });
});

describe("CheckoutDesk — before the bill is verified", () => {
  it("adjusts the bill: room charge, extras, discounts", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/checkout-requests/q1": () => json(detail()),
      "PATCH /api/v1/stays/s1": () => json({}),
      "POST /api/v1/stays/s1/charges": () => json({ id: "c3" }, 201),
      "DELETE /api/v1/stays/s1/charges/c2": () => new Response(null, { status: 204 }),
    });
    renderStaffScreen(<CheckoutDesk requestId="q1" />);

    const table = await screen.findByRole("table", { name: "Hóa đơn tạm tính" });
    expect(within(table).getByTestId("bill-total")).toHaveTextContent("1.340.000 ₫");
    expect(table).toHaveTextContent("−50.000 ₫");
    expect(screen.getByText("“Phòng sạch sẽ”")).toBeInTheDocument();

    const room = screen.getByLabelText("Tiền phòng (₫)");
    expect(room).toHaveValue("1200000");
    await userEvent.clear(room);
    await userEvent.type(room, "1.000.000");
    await userEvent.click(screen.getByRole("button", { name: "Lưu tiền phòng" }));

    const form = screen.getByRole("form", { name: "Thêm khoản" });
    const add = within(form).getByRole("button", { name: "Thêm khoản" });
    expect(add).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Mô tả"), "Trả phòng trễ");
    await userEvent.type(within(form).getByLabelText("Số tiền (₫)"), "200.000");
    await userEvent.click(add);

    await userEvent.click(screen.getByRole("button", { name: "Xóa Khách quen" }));

    await waitFor(() => {
      expect(calls(fetchMock, "PATCH", "/api/v1/stays/s1")).toEqual([
        { room_charge_vnd: 1_000_000 },
      ]);
      expect(calls(fetchMock, "POST", "/api/v1/stays/s1/charges")).toEqual([
        { kind: "EXTRA", description: "Trả phòng trễ", amount_vnd: 200_000 },
      ]);
      expect(calls(fetchMock, "DELETE", "/api/v1/stays/s1/charges/c2")).toHaveLength(1);
    });
  });

  it("cannot verify while food orders are open and links to them", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/checkout-requests/q1": () =>
        json(detail({ open_order_ids: ["o9"], open_orders: 1 })),
    });
    renderStaffScreen(<CheckoutDesk requestId="q1" />);
    const verify = await screen.findByRole("button", { name: "Chốt hóa đơn" });
    expect(verify).toBeDisabled();
    expect(screen.getByRole("link", { name: "Xem đơn của phòng" })).toHaveAttribute(
      "href",
      "/reception/orders?room=101",
    );
  });

  it("verifies with the current version and explains a race", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/checkout-requests/q1": () => json(detail({ version: 3 })),
      "POST /api/v1/checkout-requests/q1/verify": () => envelope(409, "CONFLICT"),
    });
    renderStaffScreen(<CheckoutDesk requestId="q1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Chốt hóa đơn" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("vừa được người khác cập nhật");
    expect(calls(fetchMock, "POST", "/api/v1/checkout-requests/q1/verify")).toEqual([
      { version: 3 },
    ]);
  });

  it.each([
    ["OPEN_ORDERS_EXIST", "Còn đơn đồ ăn chưa giao xong"],
    ["BILL_LOCKED", "Hóa đơn đã chốt"],
  ])("explains %s", async (code, text) => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/checkout-requests/q1": () => json(detail()),
      "POST /api/v1/checkout-requests/q1/verify": () => envelope(409, code),
    });
    renderStaffScreen(<CheckoutDesk requestId="q1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Chốt hóa đơn" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("rejects only with a reason", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/checkout-requests/q1": () => json(detail()),
      "POST /api/v1/checkout-requests/q1/reject": () => json(detail({ status: "REJECTED" })),
    });
    renderStaffScreen(<CheckoutDesk requestId="q1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Từ chối yêu cầu" }));
    const submit = screen.getByRole("button", { name: "Từ chối" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Lý do từ chối (khách sẽ thấy)"), "Còn nợ minibar");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(calls(fetchMock, "POST", "/api/v1/checkout-requests/q1/reject")).toEqual([
        { version: 0, reason: "Còn nợ minibar" },
      ]),
    );
  });
});

describe("CheckoutDesk — verified bill", () => {
  it("is read-only, prints, and completes after choosing payment and confirming", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/checkout-requests/q1": () =>
        json(
          detail({
            status: "BILLING_VERIFIED",
            bill_is_snapshot: true,
            version: 1,
            total_vnd: 1_340_000,
          }),
        ),
      "POST /api/v1/checkout-requests/q1/complete": () => json(detail({ status: "COMPLETED" })),
    });
    renderStaffScreen(<CheckoutDesk requestId="q1" />);

    const table = await screen.findByRole("table", { name: "Hóa đơn tạm tính" });
    expect(screen.getByRole("heading", { name: "Hóa đơn đã chốt" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /Xóa/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Thêm khoản" })).not.toBeInTheDocument();
    expect(screen.getByTestId("printable-bill")).toHaveTextContent("Khách sạn Hoa Sen");

    await userEvent.click(screen.getByRole("button", { name: "In hóa đơn" }));
    expect(print).toHaveBeenCalledOnce();

    expect(screen.getByRole("button", { name: "Hoàn tất trả phòng" })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Hình thức thanh toán"), "CASH");
    await userEvent.click(screen.getByRole("button", { name: "Hoàn tất trả phòng" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("sẽ bị đăng xuất ngay");
    await userEvent.click(screen.getByRole("button", { name: "Xác nhận" }));
    await waitFor(() =>
      expect(calls(fetchMock, "POST", "/api/v1/checkout-requests/q1/complete")).toEqual([
        { version: 1, payment_method: "CASH" },
      ]),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Đã hoàn tất trả phòng");
  });
});

describe("StayBill (desk check-out)", () => {
  it("shows the stay's bill with extras and print", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/stays/s1/bill": () => json({ ...BILL, open_orders: 1 }),
      "POST /api/v1/stays/s1/charges": () => envelope(409, "NEGATIVE_TOTAL"),
    });
    renderWithAuth(<StayBill stayId="s1" />);
    expect(await screen.findByTestId("bill-total")).toHaveTextContent("1.340.000 ₫");
    expect(screen.getByText("1 đơn đồ ăn chưa giao xong")).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Thêm khoản" });
    await userEvent.selectOptions(within(form).getByLabelText("Loại"), "DISCOUNT");
    await userEvent.type(within(form).getByLabelText("Mô tả"), "Giảm sốc");
    await userEvent.type(within(form).getByLabelText("Số tiền (₫)"), "9999999");
    await userEvent.click(within(form).getByRole("button", { name: "Thêm khoản" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Giảm giá lớn hơn tổng hóa đơn");
    expect(calls(fetchMock, "POST", "/api/v1/stays/s1/charges")[0]).toEqual({
      kind: "DISCOUNT",
      description: "Giảm sốc",
      amount_vnd: 9_999_999,
    });
    await userEvent.click(screen.getByRole("button", { name: "In hóa đơn" }));
    expect(print).toHaveBeenCalledOnce();
  });

  it("explains a closed stay", async () => {
    mockBackend({ ...signedIn, "GET /api/v1/stays/s1/bill": () => envelope(409, "STAY_CLOSED") });
    renderWithAuth(<StayBill stayId="s1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Kỳ lưu trú đã kết thúc");
  });
});
