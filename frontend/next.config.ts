import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// Host pubblico usato soltanto da `next dev`, senza accedere ai segreti backend.
const developmentHost = process.env.NEXT_DEV_ALLOWED_HOST?.trim();
// Il default preserva sviluppo locale; il twin Docker inietta il nome del servizio interno.
const backendOrigin = process.env.INTERNAL_BACKEND_ORIGIN?.trim() || "http://localhost:5050";

const nextConfig: NextConfig = {
  allowedDevOrigins: developmentHost
    ? [developmentHost, "*.ngrok-free.app"]
    : ["*.ngrok-free.app"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
      {
        source: "/auth/:path*",
        destination: `${backendOrigin}/auth/:path*`,
      },
      {
        source: "/webhooks/:path*",
        destination: `${backendOrigin}/webhooks/:path*`,
      },
      {
        source: "/admin/:path*",
        destination: `${backendOrigin}/admin/:path*`,
      },
      {
        source: "/login",
        destination: `${backendOrigin}/login`,
      },
      {
        source: "/register",
        destination: `${backendOrigin}/register`,
      },
      {
        source: "/logout",
        destination: `${backendOrigin}/logout`,
      },
      {
        source: "/users",
        destination: `${backendOrigin}/users`,
      },
      {
        source: "/feedbacks",
        destination: `${backendOrigin}/feedbacks`,
      },
      {
        source: "/logs",
        destination: `${backendOrigin}/logs`,
      },
      {
        source: "/setup",
        destination: `${backendOrigin}/setup`,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
