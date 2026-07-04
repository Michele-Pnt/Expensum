import createMiddleware from "next-intl/middleware";
import { routing } from "@/i18n/routing";

const proxy = createMiddleware(routing);

export default proxy;

export const config = {
  matcher: [
    "/",
    "/(it|en)",
    "/(it|en)/come-funziona-moneo",
    "/come-funziona-moneo",
    "/(it|en)/privacy",
    "/privacy",
    "/(it|en)/terms",
    "/terms",
    "/(it|en)/cookies",
    "/cookies",
  ],
};
