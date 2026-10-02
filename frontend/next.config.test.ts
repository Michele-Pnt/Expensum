import assert from "node:assert/strict";
import test from "node:test";

process.env.NEXT_DEV_ALLOWED_HOST = "preview.example.test";

test("next config accepts an explicit development host without reading backend configuration", async () => {
  const { default: nextConfig } = await import("./next.config");

  assert.deepEqual(nextConfig.allowedDevOrigins, [
    "preview.example.test",
    "*.ngrok-free.app",
  ]);
});

test("proxies the complete browser authentication lifecycle to Flask", async () => {
  const { default: nextConfig } = await import("./next.config");
  const rewrites = await nextConfig.rewrites?.();
  const rewriteList = Array.isArray(rewrites)
    ? rewrites
    : [
        ...(rewrites?.beforeFiles ?? []),
        ...(rewrites?.afterFiles ?? []),
        ...(rewrites?.fallback ?? []),
      ];
  const sources = new Set(
    rewriteList.map((rewrite) => rewrite.source),
  );

  for (const source of [
    "/forgot-password",
    "/reset-password",
    "/check-email",
    "/verify-email",
    "/verify-email/resend",
  ]) {
    assert.ok(sources.has(source), `missing auth rewrite: ${source}`);
  }
});
