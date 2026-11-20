import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RoomManager } from "@/components/reception/RoomManager";
import { StayDetail } from "@/components/reception/StayDetail";
import { envelope, json, mockBackend, renderWithAuth, session } from "../auth/helpers";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => nav,
  usePathname: () => "/reception",
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const RECEPTIONIST = {
  id: "r-1",
  email: "le.tan@hotel.test",
  full_name: "Le Tan",
  role: "RECEPTION" as const,
};
const signedIn = { "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)) };

const STAY = {
  id: "s1",
  room_id: "r101",
  room_number: "101",
  guest_name: "Tran Thi B",
  guest_count: 2,
  checkin_at: "2026-11-19T07:00:00Z",
  expected_checkout_at: "2026-11-21T05:00:00Z",
  room_charge_vnd: 1200000,
  note: null,
  status: "ACTIVE",
  code_issued_at: "2026-11-19T07:00:00Z",
  closed_at: null,
};

beforeEach(() => {
  nav.push.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

const bodyOf = (fetchMock: ReturnType<typeof mockBackend>, suffix: string, method: string) => {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url).endsWith(suffix) && (init as RequestInit).method === method,
  );
  return call ? JSON.parse(String((call[1] as RequestInit).body ?? "null")) : undefined;
};

describe("StayDetail", () => {
  it("shows the stay and saves edits", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/stays/s1": () => json(STAY),
      "PATCH /api/v1/stays/s1": () => json({ ...STAY, room_charge_vnd: 2000000 }),
    });
    renderWithAuth(<StayDetail stayId="s1" />);
    expect(await screen.findByRole("heading", { name: "Phòng 101" })).toBeInTheDocument();
    expect(screen.getByText(/1\.200\.000 ₫/)).toBeInTheDocument();

    const charge = screen.getByLabelText("Tiền phòng (VND)");
    await userEvent.clear(charge);
    await userEvent.type(charge, "2.000.000");
    await userEvent.click(screen.getByRole("button", { name: "Lưu thay đổi" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu");
    expect(bodyOf(fetchMock, "/stays/s1", "PATCH")).toMatchObject({
      guest_name: "Tran Thi B",
      guest_count: 2,
      room_charge_vnd: 2000000,
      expected_checkout_at: "2026-11-21T05:00:00.000Z",
    });
  });

  it("re-issues the code only after confirmation and shows it on a slip", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/stays/s1": () => json(STAY),
      "POST /api/v1/stays/s1/reissue-code": () =>
        json({ room_code: "WXYZ-2345", qr_payload: "hotelapp://login?code=WXYZ2345" }),
    });
    renderWithAuth(<StayDetail stayId="s1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Cấp lại mã" }));
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/reissue-code"))).toBe(false);

    const dialog = screen.getByRole("alertdialog", { name: "Cấp lại mã" });
    expect(dialog).toHaveTextContent("mọi thiết bị của khách sẽ bị đăng xuất");
    await userEvent.click(within(dialog).getByRole("button", { name: "Xác nhận" }));

    const slip = await screen.findByRole("dialog", { name: "Phiếu nhận phòng" });
    expect(within(slip).getByTestId("room-code")).toHaveTextContent("WXYZ-2345");
  });

  it("checks out after confirmation and returns to the board", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/stays/s1": () => json(STAY),
      "POST /api/v1/stays/s1/checkout": () => json({ ...STAY, status: "CLOSED" }),
    });
    renderWithAuth(<StayDetail stayId="s1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Check-out" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog", { name: "Check-out" })).getByRole("button", {
        name: "Xác nhận",
      }),
    );
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/reception"));
  });

  it("links to the bill and sends a blocked check-out to the open express request", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/stays/s1": () => json(STAY),
      "POST /api/v1/stays/s1/checkout": () =>
        json(
          {
            error: {
              code: "CHECKOUT_REQUEST_OPEN",
              message: "x",
              details: [{ checkout_request_id: "q7" }],
              request_id: "r",
            },
          },
          409,
        ),
    });
    renderWithAuth(<StayDetail stayId="s1" />);
    expect(await screen.findByRole("link", { name: "Xem hóa đơn" })).toHaveAttribute(
      "href",
      "/reception/stays/s1/bill",
    );
    await userEvent.click(screen.getByRole("button", { name: "Check-out" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog", { name: "Check-out" })).getByRole("button", {
        name: "Xác nhận",
      }),
    );
    expect(await screen.findByText(/đang có yêu cầu trả phòng nhanh/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mở yêu cầu trả phòng" })).toHaveAttribute(
      "href",
      "/reception/checkout/q7",
    );
    expect(nav.push).not.toHaveBeenCalled();
    expect(bodyOf(fetchMock, "/stays/s1/checkout", "POST")).toBeNull();
  });

  it("reports any other check-out failure", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/stays/s1": () => json(STAY),
      "POST /api/v1/stays/s1/checkout": () => envelope(500, "INTERNAL"),
    });
    renderWithAuth(<StayDetail stayId="s1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Check-out" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog", { name: "Check-out" })).getByRole("button", {
        name: "Xác nhận",
      }),
    );
    expect(await screen.findByText("Không trả phòng được, vui lòng thử lại")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Mở yêu cầu trả phòng" })).not.toBeInTheDocument();
  });

  it("is read-only once the stay is closed", async () => {
    mockBackend({ ...signedIn, "GET /api/v1/stays/s1": () => json({ ...STAY, status: "CLOSED" }) });
    renderWithAuth(<StayDetail stayId="s1" />);
    expect(await screen.findByText(/Đã trả phòng/)).toBeInTheDocument();
    expect(screen.getByLabelText("Tên khách")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Check-out" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cấp lại mã" })).not.toBeInTheDocument();
  });

  it("reports an unknown stay", async () => {
    mockBackend({ ...signedIn, "GET /api/v1/stays/nope": () => envelope(404, "NOT_FOUND") });
    renderWithAuth(<StayDetail stayId="nope" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Không tìm thấy kỳ lưu trú");
  });
});

describe("RoomManager", () => {
  const ROOMS = [
    {
      id: "r101",
      number: "101",
      floor: 1,
      room_type: "Std",
      status: "VACANT",
      is_active: true,
      open_stay: null,
    },
  ];

  it("adds a room and reloads", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/rooms": [
        () => json(ROOMS),
        () => json([...ROOMS, { ...ROOMS[0], id: "r301", number: "301", floor: 3 }]),
      ],
      "POST /api/v1/rooms": () => json({}, 201),
    });
    renderWithAuth(<RoomManager />);
    await screen.findByTestId("row-101");
    const form = screen.getByRole("form", { name: "Thêm phòng" });
    await userEvent.type(within(form).getByLabelText("Số phòng"), "301");
    await userEvent.type(within(form).getByLabelText("Tầng"), "3");
    await userEvent.click(within(form).getByRole("button", { name: "Thêm phòng" }));

    expect(await screen.findByTestId("row-301")).toBeInTheDocument();
    expect(bodyOf(fetchMock, "/api/v1/rooms", "POST")).toEqual({
      number: "301",
      floor: 3,
      room_type: null,
    });
  });

  it("explains a duplicate room number", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/rooms": () => json(ROOMS),
      "POST /api/v1/rooms": () => envelope(409, "ROOM_NUMBER_TAKEN"),
    });
    renderWithAuth(<RoomManager />);
    await screen.findByTestId("row-101");
    const form = screen.getByRole("form", { name: "Thêm phòng" });
    await userEvent.type(within(form).getByLabelText("Số phòng"), "101");
    await userEvent.click(within(form).getByRole("button", { name: "Thêm phòng" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Số phòng đã tồn tại");
  });

  it("takes a room out of service and shows the backend's refusal", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/rooms": () => json(ROOMS),
      "PATCH /api/v1/rooms/r101": () => envelope(409, "ROOM_NOT_VACANT"),
    });
    renderWithAuth(<RoomManager />);
    await userEvent.click(await screen.findByLabelText("Phòng 101 đang kinh doanh"));
    expect(bodyOf(fetchMock, "/rooms/r101", "PATCH")).toEqual({ is_active: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("Chỉ ngừng kinh doanh");
  });

  it("edits a room inline", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/rooms": () => json(ROOMS),
      "PATCH /api/v1/rooms/r101": () => json(ROOMS[0]),
    });
    renderWithAuth(<RoomManager />);
    await userEvent.click(
      within(await screen.findByTestId("row-101")).getByRole("button", { name: "Sửa" }),
    );
    const type = within(screen.getByRole("table")).getByRole("textbox", { name: "Loại phòng" });
    await userEvent.clear(type);
    await userEvent.type(type, "Deluxe");
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));
    await waitFor(() =>
      expect(bodyOf(fetchMock, "/rooms/r101", "PATCH")).toEqual({
        number: "101",
        floor: 1,
        room_type: "Deluxe",
      }),
    );
  });
});
