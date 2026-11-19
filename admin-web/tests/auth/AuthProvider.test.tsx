import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "@/lib/auth/AuthProvider";
import { envelope, json, mockBackend, renderWithAuth, session, STAFF } from "./helpers";

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="status">{auth.state.status}</span>
      {auth.state.status === "authenticated" && (
        <span data-testid="name">{auth.state.staff.full_name}</span>
      )}
      <button onClick={() => void auth.login("bep@hotel.test", "pw").catch(() => undefined)}>
        login
      </button>
      <button onClick={() => void auth.logout()}>logout</button>
      <button
        onClick={() =>
          void auth
            .authFetch<{ ok: boolean }>("/api/v1/staff/me")
            .then((r) => document.body.setAttribute("data-me", JSON.stringify(r)))
            .catch((e: Error) => document.body.setAttribute("data-me", `error:${e.message}`))
        }
      >
        me
      </button>
    </div>
  );
}

const status = () => screen.getByTestId("status").textContent;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  document.body.removeAttribute("data-me");
});

describe("AuthProvider", () => {
  it("restores the session from the refresh cookie on load", async () => {
    const fetchMock = mockBackend({ "POST /api/v1/staff/auth/refresh": () => json(session()) });
    renderWithAuth(<Probe />);
    expect(status()).toBe("loading");
    await waitFor(() => expect(status()).toBe("authenticated"));
    expect(screen.getByTestId("name")).toHaveTextContent(STAFF.full_name);
    const [, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(init.credentials).toBe("same-origin");
  });

  it("is anonymous when there is no valid refresh cookie", async () => {
    mockBackend({ "POST /api/v1/staff/auth/refresh": () => envelope(401, "UNAUTHORIZED") });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(status()).toBe("anonymous"));
  });

  it("logs in and never stores the token in web storage", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => envelope(401, "UNAUTHORIZED"),
      "POST /api/v1/staff/auth/login": () => json(session("secret-access-token")),
    });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(status()).toBe("anonymous"));
    act(() => screen.getByText("login").click());
    await waitFor(() => expect(status()).toBe("authenticated"));

    const stored = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    expect(stored).not.toContain("secret-access-token");
    expect(document.cookie).not.toContain("secret-access-token");
  });

  it("authFetch refreshes once on 401 and retries with the new token", async () => {
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": [() => json(session("old")), () => json(session("new"))],
      "GET /api/v1/staff/me": [() => envelope(401, "UNAUTHORIZED"), () => json({ ok: true })],
    });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(status()).toBe("authenticated"));

    act(() => screen.getByText("me").click());
    await waitFor(() => expect(document.body.getAttribute("data-me")).toBe('{"ok":true}'));

    const meCalls = fetchMock.mock.calls.filter(([url]) => url.toString().endsWith("/me"));
    const auths = meCalls.map(
      ([, init]) => (init as RequestInit).headers as Record<string, string>,
    );
    expect(auths.map((h) => h.Authorization)).toEqual(["Bearer old", "Bearer new"]);
  });

  it("signs out when the refresh after a 401 also fails", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": [() => json(session()), () => envelope(401, "X")],
      "GET /api/v1/staff/me": () => envelope(401, "UNAUTHORIZED"),
    });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(status()).toBe("authenticated"));
    act(() => screen.getByText("me").click());
    await waitFor(() => expect(status()).toBe("anonymous"));
    expect(document.body.getAttribute("data-me")).toMatch(/^error:/);
  });

  it("refreshes about a minute before the access token expires", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session("t", 120)),
    });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(status()).toBe("authenticated"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("logout clears the session even if the request fails", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session()),
      "POST /api/v1/staff/auth/logout": () => Promise.reject(new TypeError("offline")),
    });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(status()).toBe("authenticated"));
    act(() => screen.getByText("logout").click());
    await waitFor(() => expect(status()).toBe("anonymous"));
  });

  it("useAuth outside the provider is a programming error", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => renderWithAuthless()).toThrow(/inside <AuthProvider>/);
    spy.mockRestore();
  });
});

function renderWithAuthless() {
  function Bare() {
    useAuth();
    return null;
  }
  render(<Bare />);
}
