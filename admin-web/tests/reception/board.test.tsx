import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RoomBoard } from "@/components/reception/RoomBoard";
import { defaultCheckoutInput, localInputToIso } from "@/lib/reception/types";
import { envelope, json, mockBackend, renderWithAuth, session } from "../auth/helpers";

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
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

const stay = {
  id: "stay-1",
  guest_name: "Tran Thi B",
  guest_count: 2,
  checkin_at: "2026-11-19T07:00:00Z",
  expected_checkout_at: "2026-11-21T05:00:00Z",
  status: "ACTIVE",
};

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
  {
    id: "r102",
    number: "102",
    floor: 1,
    room_type: "Std",
    status: "OCCUPIED",
    is_active: true,
    open_stay: stay,
  },
  {
    id: "r201",
    number: "201",
    floor: 2,
    room_type: "Std",
    status: "CLEANING",
    is_active: true,
    open_stay: null,
  },
  {
    id: "r999",
    number: "999",
    floor: 9,
    room_type: "Old",
    status: "VACANT",
    is_active: false,
    open_stay: null,
  },
];

const signedIn = { "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)) };

afterEach(() => vi.unstubAllGlobals());

describe("RoomBoard", () => {
  it("shows active rooms with their status and actions", async () => {
    mockBackend({ ...signedIn, "GET /api/v1/rooms": () => json(ROOMS) });
    renderWithAuth(<RoomBoard />);

    const vacant = await screen.findByTestId("room-101");
    expect(vacant).toHaveAttribute("data-status", "VACANT");
    expect(within(vacant).getByRole("button", { name: "Check-in" })).toBeInTheDocument();

    const occupied = screen.getByTestId("room-102");
    expect(occupied).toHaveTextContent("Tran Thi B");
    expect(within(occupied).getByRole("link", { name: "Chi tiết" })).toHaveAttribute(
      "href",
      "/reception/stays/stay-1",
    );
    expect(within(screen.getByTestId("room-201")).getByText("Đánh dấu đã dọn")).toBeInTheDocument();
    expect(screen.queryByTestId("room-999")).not.toBeInTheDocument();
  });

  it("filters by floor", async () => {
    mockBackend({ ...signedIn, "GET /api/v1/rooms": () => json(ROOMS) });
    renderWithAuth(<RoomBoard />);
    await screen.findByTestId("room-101");
    await userEvent.selectOptions(screen.getByLabelText(/Tầng/), "2");
    expect(screen.queryByTestId("room-101")).not.toBeInTheDocument();
    expect(screen.getByTestId("room-201")).toBeInTheDocument();
  });

  it("checks a guest in and shows the slip with code and QR exactly once", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/rooms": () => json(ROOMS),
      "POST /api/v1/stays": () =>
        json(
          {
            room_code: "K7M2-9XPQ",
            qr_payload: "hotelapp://login?code=K7M29XPQ",
            stay: { ...stay, room_number: "101", room_id: "r101", room_charge_vnd: 1200000 },
          },
          201,
        ),
    });
    renderWithAuth(<RoomBoard />);
    await userEvent.click(
      within(await screen.findByTestId("room-101")).getByRole("button", { name: "Check-in" }),
    );
    await userEvent.type(screen.getByLabelText("Tên khách (không bắt buộc)"), "Tran Thi B");
    await userEvent.type(screen.getByLabelText("Tiền phòng (VND)"), "1.200.000");
    await userEvent.click(screen.getByRole("button", { name: "Check-in và cấp mã" }));

    const slip = await screen.findByRole("dialog", { name: "Phiếu nhận phòng" });
    expect(within(slip).getByTestId("room-code")).toHaveTextContent("K7M2-9XPQ");
    expect(within(slip).getByLabelText("Mã QR đăng nhập").tagName.toLowerCase()).toBe("svg");

    const post = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/v1/stays"));
    const body = JSON.parse((post?.[1] as RequestInit).body as string);
    expect(body).toEqual({
      room_id: "r101",
      guest_name: "Tran Thi B",
      guest_count: 1,
      expected_checkout_at: localInputToIso(defaultCheckoutInput()),
      room_charge_vnd: 1200000,
      note: null,
    });

    await userEvent.click(within(slip).getByRole("button", { name: "Đóng" }));
    expect(screen.queryByText("K7M2-9XPQ")).not.toBeInTheDocument();
  });

  it("explains a room that was taken meanwhile", async () => {
    mockBackend({
      ...signedIn,
      "GET /api/v1/rooms": () => json(ROOMS),
      "POST /api/v1/stays": () => envelope(409, "ROOM_NOT_VACANT"),
    });
    renderWithAuth(<RoomBoard />);
    await userEvent.click(
      within(await screen.findByTestId("room-101")).getByRole("button", { name: "Check-in" }),
    );
    await userEvent.type(screen.getByLabelText("Tiền phòng (VND)"), "500000");
    await userEvent.click(screen.getByRole("button", { name: "Check-in và cấp mã" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Phòng không còn trống");
  });

  it("marks a cleaned room vacant and reloads", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/rooms": [
        () => json(ROOMS),
        () => json(ROOMS.map((r) => (r.id === "r201" ? { ...r, status: "VACANT" } : r))),
      ],
      "POST /api/v1/rooms/r201/mark-vacant": () => json({ ...ROOMS[2], status: "VACANT" }),
    });
    renderWithAuth(<RoomBoard />);
    await userEvent.click(await screen.findByText("Đánh dấu đã dọn"));
    await waitFor(() =>
      expect(screen.getByTestId("room-201")).toHaveAttribute("data-status", "VACANT"),
    );
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/mark-vacant"))).toBe(true);
  });
});
