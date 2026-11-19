import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/components/auth/LoginForm";
import { StaffGuard } from "@/components/auth/StaffGuard";
import { StaffShell } from "@/components/auth/StaffShell";
import { areaOf, canAccess, roleHome } from "@/lib/auth/roles";
import { envelope, json, mockBackend, renderWithAuth, session, STAFF } from "./helpers";

const nav = vi.hoisted(() => ({ replace: vi.fn(), pathname: "/kitchen" }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => nav.pathname,
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

beforeEach(() => {
  nav.replace.mockClear();
  nav.pathname = "/kitchen";
});
afterEach(() => vi.unstubAllGlobals());

describe("roles", () => {
  it("maps roles to areas", () => {
    expect(roleHome("RECEPTION")).toBe("/reception");
    expect(areaOf("/kitchen/menu")).toBe("kitchen");
    expect(areaOf("/account")).toBeNull();
    expect(canAccess("KITCHEN", "/kitchen")).toBe(true);
    expect(canAccess("KITCHEN", "/reception/rooms")).toBe(false);
    expect(canAccess("HOUSEKEEPING", "/account")).toBe(true);
  });
});

describe("LoginForm", () => {
  const anonymous = { "POST /api/v1/staff/auth/refresh": () => envelope(401, "UNAUTHORIZED") };

  async function submit(email = "bep@hotel.test", password = "secret-pw") {
    await userEvent.type(screen.getByLabelText("Email"), email);
    await userEvent.type(screen.getByLabelText("Mật khẩu"), password);
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
  }

  it("signs in and goes to the role's area", async () => {
    mockBackend({ ...anonymous, "POST /api/v1/staff/auth/login": () => json(session()) });
    renderWithAuth(<LoginForm />);
    await submit();
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/kitchen"));
  });

  it("shows one generic message for wrong credentials and clears the password", async () => {
    mockBackend({
      ...anonymous,
      "POST /api/v1/staff/auth/login": () => envelope(401, "UNAUTHORIZED"),
    });
    renderWithAuth(<LoginForm />);
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Email hoặc mật khẩu không đúng");
    expect(screen.getByLabelText("Mật khẩu")).toHaveValue("");
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("tells how long to wait when rate limited", async () => {
    mockBackend({
      ...anonymous,
      "POST /api/v1/staff/auth/login": () =>
        envelope(429, "RATE_LIMITED", { "Retry-After": "840" }),
    });
    renderWithAuth(<LoginForm />);
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("14 phút");
  });

  it("reports a network failure", async () => {
    mockBackend({
      ...anonymous,
      "POST /api/v1/staff/auth/login": () => Promise.reject(new TypeError("offline")),
    });
    renderWithAuth(<LoginForm />);
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Không kết nối được");
  });
});

describe("StaffGuard", () => {
  it("sends anonymous users to the login page", async () => {
    mockBackend({ "POST /api/v1/staff/auth/refresh": () => envelope(401, "UNAUTHORIZED") });
    renderWithAuth(<StaffGuard>secret area</StaffGuard>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("secret area")).not.toBeInTheDocument();
  });

  it("renders the page in the user's own area", async () => {
    mockBackend({ "POST /api/v1/staff/auth/refresh": () => json(session()) });
    renderWithAuth(<StaffGuard>kitchen queue</StaffGuard>);
    expect(await screen.findByText("kitchen queue")).toBeInTheDocument();
  });

  it("shows 403 with a way back when opening another role's area", async () => {
    nav.pathname = "/reception/rooms";
    mockBackend({ "POST /api/v1/staff/auth/refresh": () => json(session()) });
    renderWithAuth(<StaffGuard>reception page</StaffGuard>);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Không có quyền truy cập");
    expect(screen.getByRole("link", { name: "Về trang của tôi" })).toHaveAttribute(
      "href",
      "/kitchen",
    );
    expect(screen.queryByText("reception page")).not.toBeInTheDocument();
  });
});

describe("StaffShell", () => {
  it("shows the staff member and signs out", async () => {
    mockBackend({
      "POST /api/v1/staff/auth/refresh": () => json(session()),
      "POST /api/v1/staff/auth/logout": () => json(null, 204),
    });
    renderWithAuth(<StaffShell>content</StaffShell>);
    expect(await screen.findByTestId("staff-name")).toHaveTextContent(STAFF.full_name);
    expect(screen.getByRole("link", { name: "Bếp" })).toHaveAttribute("href", "/kitchen");

    await userEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login"));
  });
});
