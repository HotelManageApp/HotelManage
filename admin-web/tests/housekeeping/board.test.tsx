import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HousekeepingBoard } from "@/components/housekeeping/HousekeepingBoard";
import { HousekeepingList } from "@/components/reception/HousekeepingList";
import { RoomBoard } from "@/components/reception/RoomBoard";
import { byRoom, type StaffHkRequest } from "@/lib/housekeeping/types";
import { envelope, json, mockBackend, session } from "../auth/helpers";
import { renderStaffScreen, sseRoute } from "../realtime/sse";

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/reception",
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const LAN = {
  id: "hk-lan",
  email: "lan@h.test",
  full_name: "Nguyen Thi Lan",
  role: "HOUSEKEEPING" as const,
};
const RECEPTIONIST = {
  id: "r-1",
  email: "lt@h.test",
  full_name: "Le Tan",
  role: "RECEPTION" as const,
};

function job(overrides: Partial<StaffHkRequest> = {}): StaffHkRequest {
  return {
    id: "h1",
    type: "CLEANING",
    status: "REQUESTED",
    amenities: [],
    preferred_time: null,
    note: null,
    source: "APP",
    assignee: null,
    cancel_reason: null,
    created_at: new Date(Date.now() - 5 * 60000).toISOString(),
    updated_at: new Date().toISOString(),
    version: 0,
    room_number: "101",
    do_not_disturb: false,
    guest_name: null,
    assigned_to: null,
    assignee_full_name: null,
    overdue: false,
    ...overrides,
  };
}

type Fetch = ReturnType<typeof mockBackend>;
const bodiesOf = (fetchMock: Fetch, suffix: string) =>
  fetchMock.mock.calls
    .filter(([url]) => String(url).endsWith(suffix))
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));
const listCalls = (fetchMock: Fetch) =>
  fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/v1/housekeeping-requests")).length;

afterEach(() => vi.unstubAllGlobals());

describe("HousekeepingBoard", () => {
  it("shows waiting jobs with amenities, DND and overdue, and only a claim button", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, LAN)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/housekeeping-requests": () =>
        json([
          job({
            id: "h1",
            type: "AMENITY",
            amenities: [{ code: "TOWEL", quantity: 2 }],
            note: "Để trước cửa",
          }),
          job({ id: "h2", room_number: "202", do_not_disturb: true, overdue: true }),
          job({
            id: "h3",
            room_number: "303",
            status: "IN_PROGRESS",
            assigned_to: "hk-other",
            assignee_full_name: "Tran Van Minh",
          }),
        ]),
    });
    renderStaffScreen(<HousekeepingBoard />);

    const amenity = await screen.findByTestId("hk-h1");
    expect(amenity).toHaveTextContent("Đồ dùng");
    expect(amenity).toHaveTextContent("2 × Khăn tắm");
    expect(amenity).toHaveTextContent("Để trước cửa");
    expect(amenity).toHaveTextContent("Càng sớm càng tốt");
    expect(
      within(amenity)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Nhận việc"]);

    const dnd = screen.getByTestId("hk-h2");
    expect(dnd).toHaveTextContent("Không làm phiền");
    expect(dnd.className).toContain("border-red-600");

    const taken = screen.getByTestId("hk-h3");
    expect(taken).toHaveTextContent("Tran Van Minh đang phụ trách");
    expect(within(taken).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Việc chờ (2)" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("claims a job, then starts and finishes it from My jobs", async () => {
    let state: StaffHkRequest = job();
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, LAN)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/housekeeping-requests": () => json([state]),
      "POST /api/v1/housekeeping-requests/h1/transition": (_url, init) => {
        const { to } = JSON.parse(String(init.body)) as { to: StaffHkRequest["status"] };
        state = {
          ...state,
          status: to,
          version: state.version + 1,
          assigned_to: to === "REQUESTED" ? null : LAN.id,
          assignee_full_name: to === "REQUESTED" ? null : LAN.full_name,
        };
        return json(state);
      },
    });
    renderStaffScreen(<HousekeepingBoard />);

    await userEvent.click(await screen.findByRole("button", { name: "Nhận việc" }));
    expect(await screen.findByRole("tab", { name: "Việc của tôi (1)" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await userEvent.click(await screen.findByRole("button", { name: "Bắt đầu" }));
    await userEvent.click(await screen.findByRole("button", { name: "Hoàn tất" }));

    await waitFor(() =>
      expect(bodiesOf(fetchMock, "/h1/transition")).toEqual([
        { to: "ASSIGNED", version: 0 },
        { to: "IN_PROGRESS", version: 1 },
        { to: "DONE", version: 2 },
      ]),
    );
    expect(await screen.findByText("Bạn chưa nhận việc nào")).toBeInTheDocument();
  });

  it("hands a claimed job back", async () => {
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, LAN)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/housekeeping-requests": () =>
        json([job({ status: "ASSIGNED", version: 1, assigned_to: LAN.id })]),
      "POST /api/v1/housekeeping-requests/h1/transition": () => json(job()),
    });
    renderStaffScreen(<HousekeepingBoard />);

    await userEvent.click(await screen.findByRole("tab", { name: "Việc của tôi (1)" }));
    await userEvent.click(screen.getByRole("button", { name: "Trả lại" }));
    await waitFor(() =>
      expect(bodiesOf(fetchMock, "/h1/transition")).toEqual([{ to: "REQUESTED", version: 1 }]),
    );
  });

  it("explains a job someone else just claimed", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, LAN)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/housekeeping-requests": () => json([job()]),
      "POST /api/v1/housekeeping-requests/h1/transition": () => envelope(409, "CONFLICT"),
    });
    renderStaffScreen(<HousekeepingBoard />);
    await userEvent.click(await screen.findByRole("button", { name: "Nhận việc" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("vừa được người khác cập nhật");
  });

  it("explains a job that belongs to someone else", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, LAN)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/housekeeping-requests": () =>
        json([job({ status: "ASSIGNED", version: 1, assigned_to: LAN.id })]),
      "POST /api/v1/housekeeping-requests/h1/transition": () => envelope(403, "FORBIDDEN"),
    });
    renderStaffScreen(<HousekeepingBoard />);
    await userEvent.click(await screen.findByRole("tab", { name: "Việc của tôi (1)" }));
    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("nhân viên khác phụ trách");
  });

  it("reloads on housekeeping and do-not-disturb events, not on food orders", async () => {
    const sse = sseRoute();
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, LAN)),
      "GET /api/v1/staff/events": sse.handler,
      "GET /api/v1/housekeeping-requests": () => json([job()]),
    });
    renderStaffScreen(<HousekeepingBoard />);
    await screen.findByTestId("hk-h1");
    await waitFor(() => expect(listCalls(fetchMock)).toBeGreaterThanOrEqual(2));
    const before = listCalls(fetchMock);

    act(() => sse.push({ entity_type: "FOOD_ORDER", status: "PENDING", room_number: "101" }));
    act(() =>
      sse.push({
        event: "do_not_disturb",
        entity_type: "STAY",
        status: "DND_ON",
        room_number: "101",
      }),
    );
    await waitFor(() => expect(listCalls(fetchMock)).toBe(before + 1));
    act(() => sse.push({ entity_type: "HOUSEKEEPING", status: "REQUESTED", room_number: "102" }));
    await waitFor(() => expect(listCalls(fetchMock)).toBe(before + 2));
  });
});

describe("HousekeepingList (reception)", () => {
  it("shows who is on each job and cancels a waiting one with a reason", async () => {
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/housekeeping-requests": () =>
        json([
          job({ guest_name: "Tran Thi B", do_not_disturb: true }),
          job({
            id: "h2",
            room_number: "202",
            status: "IN_PROGRESS",
            assigned_to: LAN.id,
            assignee_full_name: LAN.full_name,
          }),
        ]),
      "POST /api/v1/housekeeping-requests/h1/cancel": () => json(job({ status: "CANCELLED" })),
    });
    renderStaffScreen(<HousekeepingList />);

    const waiting = await screen.findByTestId("hk-row-h1");
    expect(waiting).toHaveTextContent("Tran Thi B");
    expect(waiting).toHaveTextContent("Không làm phiền");
    const working = screen.getByTestId("hk-row-h2");
    expect(working).toHaveTextContent("Nguyen Thi Lan");
    expect(working).toHaveTextContent("Đang làm");
    expect(within(working).queryByRole("button")).not.toBeInTheDocument();

    await userEvent.click(within(waiting).getByRole("button", { name: "Hủy yêu cầu phòng 101" }));
    const submit = within(waiting).getByRole("button", { name: "Hủy yêu cầu" });
    expect(submit).toBeDisabled();
    await userEvent.type(
      within(waiting).getByLabelText("Lý do hủy (khách sẽ thấy)"),
      "Khách ra ngoài",
    );
    await userEvent.click(submit);
    await waitFor(() =>
      expect(bodiesOf(fetchMock, "/h1/cancel")).toEqual([{ version: 0, reason: "Khách ra ngoài" }]),
    );
  });

  it("explains a request claimed before the cancel went through", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/housekeeping-requests": () => json([job()]),
      "POST /api/v1/housekeeping-requests/h1/cancel": () => envelope(409, "INVALID_TRANSITION"),
    });
    renderStaffScreen(<HousekeepingList />);
    await userEvent.click(await screen.findByRole("button", { name: "Hủy yêu cầu phòng 101" }));
    await userEvent.type(screen.getByLabelText("Lý do hủy (khách sẽ thấy)"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Hủy yêu cầu" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("vừa được nhận hoặc cập nhật");
  });
});

describe("Room board housekeeping badges", () => {
  it("marks rooms with do-not-disturb, waiting and in-progress cleaning", async () => {
    const room = (id: string, number: string) => ({
      id,
      number,
      floor: 1,
      room_type: "Std",
      status: "OCCUPIED",
      is_active: true,
      open_stay: null,
    });
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/rooms": () => json([room("r1", "101"), room("r2", "102"), room("r3", "103")]),
      "GET /api/v1/housekeeping-requests": () =>
        json([
          job({ room_number: "101", do_not_disturb: true }),
          job({ id: "h2", room_number: "102", status: "IN_PROGRESS" }),
          job({ id: "h3", room_number: "103", status: "DONE", do_not_disturb: true }),
        ]),
    });
    renderStaffScreen(<RoomBoard />);

    const r101 = await screen.findByTestId("room-101");
    await waitFor(() => expect(r101).toHaveTextContent("Không làm phiền"));
    expect(r101).toHaveTextContent("Chờ dọn");
    expect(screen.getByTestId("room-102")).toHaveTextContent("Đang dọn");
    expect(screen.getByTestId("room-103")).not.toHaveTextContent(/Không làm phiền|dọn/);
  });

  it("still shows the rooms when housekeeping requests cannot be read", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)),
      "GET /api/v1/staff/events": sseRoute().handler,
      "GET /api/v1/rooms": () =>
        json([
          {
            id: "r1",
            number: "101",
            floor: 1,
            room_type: null,
            status: "VACANT",
            is_active: true,
            open_stay: null,
          },
        ]),
      "GET /api/v1/housekeeping-requests": () => envelope(500, "INTERNAL"),
    });
    renderStaffScreen(<RoomBoard />);
    expect(await screen.findByTestId("room-101")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("an in-progress job wins over a waiting one in the same room", () => {
    const map = byRoom([
      job({ id: "a", room_number: "101" }),
      job({ id: "b", room_number: "101", status: "IN_PROGRESS" }),
      job({ id: "c", room_number: "101" }),
    ]);
    expect(map.get("101")).toEqual({ doNotDisturb: false, work: "cleaning" });
  });
});
