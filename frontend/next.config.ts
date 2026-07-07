import type { NextConfig } from "next";
import fs from "fs";
import path from "path";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// Carica l'URL di ngrok dal .env della root
const envPath = path.resolve(process.cwd(), "../.env");
let ngrokHost = "";
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf-8");
  const match = envContent.match(/^WEBAPP_BASE_URL=https:\/\/([^/\s]+)/m);
  if (match) ngrokHost = match[1];
}

const nextConfig: NextConfig = {
  allowedDevOrigins: ngrokHost ? [ngrokHost, "*.ngrok-free.app"] : ["*.ngrok-free.app"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:5000/api/:path*",
      },
      {
        source: "/auth/:path*",
        destination: "http://localhost:5000/auth/:path*",
      },
      {
        source: "/webhooks/:path*",
        destination: "http://localhost:5000/webhooks/:path*",
      },
      {
        source: "/admin/:path*",
        destination: "http://localhost:5000/admin/:path*",
      },
      {
        source: "/login",
        destination: "http://localhost:5000/login",
      },
      {
        source: "/register",
        destination: "http://localhost:5000/register",
      },
      {
        source: "/logout",
        destination: "http://localhost:5000/logout",
      },
      {
        source: "/users",
        destination: "http://localhost:5000/users",
      },
      {
        source: "/feedbacks",
        destination: "http://localhost:5000/feedbacks",
      },
      {
        source: "/logs",
        destination: "http://localhost:5000/logs",
      },
      {
        source: "/setup",
        destination: "http://localhost:5000/setup",
      },
    ];
  },
};

export default withNextIntl(nextConfig);
