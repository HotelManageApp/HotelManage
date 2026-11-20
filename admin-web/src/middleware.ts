import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // All pages except Next internals and static files.
  matcher: ["/((?!api|_next|_vercel|.*\..*).*)"],
};
