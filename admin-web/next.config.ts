import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  // The browser calls /api/v1/* on the web origin and Next proxies it to backend-api.
  // Same origin => no CORS, and the HttpOnly refresh cookie (Path=/api/v1/staff/auth) stays
  // first-party. BACKEND_URL is read when the server starts (T56 sets it for deploy).
  async rewrites() {
    const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
};

export default withNextIntl(nextConfig);
