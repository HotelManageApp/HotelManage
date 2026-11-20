// T55 load test: 50 guests at the same time (CONSTRAINTS C6).
//
// Each virtual guest uses a real stay token and loops: open the app (/guest/me), browse the
// menu, place an order, follow it (list + detail), poll its housekeeping list.
// Pass bar: no 5xx, p95 < 500 ms for every API call (the chatbot is not part of this test).
//
// Tokens come from the backend dev CLI, never from a password in this file:
//   docker exec <backend> python -m app.cli seed-dev-stays --count 50 > tokens.json
//   k6 run -e BASE_URL=http://localhost:8010 -e TOKENS=tokens.json loadtest/guest_flow.js
// Clean up afterwards: python -m app.cli seed-dev-stays --close

import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";
import { Counter } from "k6/metrics";

// 409 TOO_MANY_PENDING_ORDERS (5 pending orders per stay) is a business answer, not a failure.
http.setResponseCallback(http.expectedStatuses(200, 201, 409));
const serverErrors = new Counter("server_errors_5xx");

const BASE = `${__ENV.BASE_URL || "http://localhost:8010"}/api/v1`;
const tokens = new SharedArray("tokens", () =>
  JSON.parse(open(__ENV.TOKENS || "tokens.json")).map((s) => s.token),
);

export const options = {
  scenarios: {
    guests: {
      executor: "constant-vus",
      vus: 50,
      duration: __ENV.DURATION || "2m",
    },
  },
  thresholds: {
    http_req_failed: ["rate==0"],
    server_errors_5xx: ["count==0"],
    checks: ["rate>0.99"],
    "http_req_duration{kind:api}": ["p(95)<500"],
    "http_req_duration{name:place_order}": ["p(95)<500"],
  },
};

function counted(response) {
  if (response.status >= 500) serverErrors.add(1);
  return response;
}

function get(path, token, name) {
  return counted(
    http.get(`${BASE}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      tags: { kind: "api", name },
    }),
  );
}

export default function () {
  const token = tokens[(__VU - 1) % tokens.length];

  const me = get("/guest/me", token, "me");
  check(me, { "me 200": (r) => r.status === 200 });

  const menu = get("/guest/menu", token, "menu");
  check(menu, { "menu 200": (r) => r.status === 200 });
  const items = menu.status === 200 ? menu.json("items").filter((i) => i.available) : [];
  sleep(1);

  if (items.length > 0 && menu.json("is_open_now")) {
    const dish = items[Math.floor(Math.random() * items.length)];
    const order = counted(http.post(
      `${BASE}/guest/orders`,
      JSON.stringify({ items: [{ item_id: dish.item_id, quantity: 1 }] }),
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          "Idempotency-Key": `load-${__VU}-${__ITER}-${Date.now()}`,
        },
        tags: { kind: "api", name: "place_order" },
      },
    ));
    // 409 TOO_MANY_PENDING_ORDERS is the business limit (5 pending per stay), not an error.
    check(order, { "order 201/409": (r) => r.status === 201 || r.status === 409 });
    if (order.status === 201) {
      const id = order.json("id");
      check(get(`/guest/orders/${id}`, token, "order_detail"), {
        "order detail 200": (r) => r.status === 200,
      });
    }
  }
  sleep(1);

  check(get("/guest/orders", token, "orders"), { "orders 200": (r) => r.status === 200 });
  check(get("/guest/housekeeping-requests", token, "housekeeping"), {
    "housekeeping 200": (r) => r.status === 200,
  });
  sleep(2);
}
