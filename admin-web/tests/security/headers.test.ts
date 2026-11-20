import { describe, expect, it } from "vitest";
import nextConfig, { SECURITY_HEADERS } from "../../next.config";

describe("security headers (T54)", () => {
  it("are sent on every page", async () => {
    const rules = await nextConfig.headers?.();
    expect(rules).toEqual([{ source: "/:path*", headers: SECURITY_HEADERS }]);
    const byName = Object.fromEntries(SECURITY_HEADERS.map((h) => [h.key, h.value]));
    expect(byName["X-Frame-Options"]).toBe("DENY");
    expect(byName["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
    expect(byName["X-Content-Type-Options"]).toBe("nosniff");
  });
});
