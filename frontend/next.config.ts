import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
        source: "/admin/:path*",
        destination: "http://localhost:5000/admin/:path*",
      },
      {
        source: "/login",
        destination: "http://localhost:5000/login",
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

export default nextConfig;
