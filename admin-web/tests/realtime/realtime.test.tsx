import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RealtimeBar, toastFor } from "@/components/layout/RealtimeBar";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import { SseParser } from "@/lib/realtime/sseParser";
import {
  StaffEventsProvider,
  useStaffEvents,
  type StaffEvent,
} from "@/lib/realtime/useStaffEvents";
import viMessages from "../../messages/vi.json";
import { BASE, json, session } from "../auth/helpers";

const KITCHEN = { id: "k", email: "k@h.test", full_name: "Bep", role: "KITCHEN" as const };

function event(overrides: Partial<StaffEvent> = {}): StaffEvent {
  return {
    event: "status_changed",
    entity_type: "FOOD_ORDER",
    entity_id: "o1",
    status: "PENDING",
    room_number: "101",
    actor: "GUEST",
    occurred_at: "2026-11-19T08:00:00Z",
    ...overrides,
  };
}

/** A fake SSE endpoint: each connection gets a stream the test can write to or close. */
function sseBackend() {
  const streams: ReadableStreamDefaultController<Uint8Array>[] = [];
  const encoder = new TextEncoder();
  const fetchMock = vi.fn(async (input: URL | string, init: RequestInit = {}) => {
    const path = new URL(input.toString()).pathname;
    if (path === "/api/v1/staff/auth/refresh") return json(session("tok", 900, KITCHEN));
    if (path === "/api/v1/staff/events") {
      const headers = init.headers as Record<string, string>;
      expect(headers.Authorization).toBe("Bearer tok");
      return new Response(new ReadableStream<Uint8Array>({ start: (c) => void streams.push(c) }), {
        headers: { "Content-Type": "text/event-stream" },
      });
    }
    throw new Error(`unexpected ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    send(controllerIndex: number, chunk: string) {
      streams[controllerIndex]?.enqueue(encoder.encode(chunk));
    },
    close(controllerIndex: number) {
      streams[controllerIndex]?.close();
    },
    get connections() {
      return streams.length;
    },
  };
}

function wrap(ui: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="vi" messages={viMessages} timeZone="Asia/Ho_Chi_Minh">
      <AuthProvider baseUrl={BASE}>
        <StaffEventsProvider baseUrl={BASE}>{ui}</StaffEventsProvider>
      </AuthProvider>
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("SseParser", () => {
  it("handles events split across chunks and ignores comments", () => {
    const parser = new SseParser();
    expect(parser.push(": connected\n\nevent: status_")).toEqual([]);
    expect(parser.push('changed\ndata: {"a":1}\n')).toEqual([]);
    expect(parser.push("\n: ping\n\nevent: order_overdue\ndata: {}\n\n")).toEqual([
      { event: "status_changed", data: '{"a":1}' },
      { event: "order_overdue", data: "{}" },
    ]);
  });

  it("joins multi-line data and accepts CRLF", () => {
    expect(new SseParser().push("data: a\r\ndata: b\r\n\r\n")).toEqual([
      { event: "message", data: "a\nb" },
    ]);
  });
});

describe("toastFor", () => {
  it("only toasts what each role works on", () => {
    expect(toastFor("KITCHEN", event())).toBe("newOrder");
    expect(toastFor("HOUSEKEEPING", event())).toBeNull();
    expect(
      toastFor("HOUSEKEEPING", event({ entity_type: "HOUSEKEEPING", status: "REQUESTED" })),
    ).toBe("newHousekeeping");
    expect(
      toastFor("RECEPTION", event({ entity_type: "CHECKOUT", status: "CHECKOUT_REQUESTED" })),
    ).toBe("newCheckout");
    expect(toastFor("KITCHEN", event({ status: "CONFIRMED" }))).toBeNull();
    expect(toastFor("RECEPTION", event({ event: "order_overdue" }))).toBe("orderOverdue");
    expect(toastFor("HOUSEKEEPING", event({ event: "order_overdue" }))).toBeNull();
  });
});

function Recorder({ onReconnect }: { onReconnect: () => void }) {
  const seen: string[] = [];
  const state = useStaffEvents((e) => {
    seen.push(`${e.event}:${e.status}`);
    document.body.dataset.seen = seen.join(",");
  }, onReconnect);
  return <span data-testid="state">{state}</span>;
}

describe("useStaffEvents", () => {
  it("delivers events and reconnects with backoff, reloading after each connect", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const backend = sseBackend();
    const reconnects = vi.fn();
    wrap(<Recorder onReconnect={reconnects} />);

    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("open"));
    expect(reconnects).toHaveBeenCalledTimes(1);

    act(() =>
      backend.send(
        0,
        'event: status_changed\ndata: {"status":"PENDING","entity_type":"FOOD_ORDER"}\n\n',
      ),
    );
    await waitFor(() => expect(document.body.dataset.seen).toBe("status_changed:PENDING"));

    act(() => backend.close(0));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("closed"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await waitFor(() => expect(backend.connections).toBe(2));
    await waitFor(() => expect(reconnects).toHaveBeenCalledTimes(2));
  });
});

describe("RealtimeBar", () => {
  it("shows the connection and a toast for a new order; sound can be switched on", async () => {
    const backend = sseBackend();
    wrap(<RealtimeBar />);
    await waitFor(() =>
      expect(screen.getByTestId("connection")).toHaveAttribute("data-state", "open"),
    );
    expect(screen.getByText("Đã kết nối")).toBeInTheDocument();

    act(() => backend.send(0, `event: status_changed\ndata: ${JSON.stringify(event())}\n\n`));
    expect(await screen.findByRole("status")).toHaveTextContent("Đơn đồ ăn mới — phòng 101");

    await userEvent.click(screen.getByRole("button", { name: "Âm báo: tắt" }));
    expect(window.localStorage.getItem("staff-sound-enabled")).toBe("1");
    expect(screen.getByRole("button", { name: "Âm báo: bật" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
