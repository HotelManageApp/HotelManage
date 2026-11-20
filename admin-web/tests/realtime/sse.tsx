import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import { StaffEventsProvider, type StaffEvent } from "@/lib/realtime/useStaffEvents";
import viMessages from "../../messages/vi.json";
import { BASE } from "../auth/helpers";

/** A route for mockBackend that serves the staff SSE stream and lets tests push events. */
export function sseRoute() {
  const controllers: ReadableStreamDefaultController<Uint8Array>[] = [];
  const encoder = new TextEncoder();
  return {
    handler: () =>
      new Response(new ReadableStream<Uint8Array>({ start: (c) => void controllers.push(c) }), {
        headers: { "Content-Type": "text/event-stream" },
      }),
    push(event: Partial<StaffEvent> & { entity_type: StaffEvent["entity_type"] }) {
      const name = event.event ?? "status_changed";
      const line = `event: ${name}\ndata: ${JSON.stringify({ ...event, event: name })}\n\n`;
      controllers.at(-1)?.enqueue(encoder.encode(line));
    },
  };
}

export function renderStaffScreen(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="vi" messages={viMessages} timeZone="Asia/Ho_Chi_Minh">
      <AuthProvider baseUrl={BASE}>
        <StaffEventsProvider baseUrl={BASE}>{ui}</StaffEventsProvider>
      </AuthProvider>
    </NextIntlClientProvider>,
  );
}
