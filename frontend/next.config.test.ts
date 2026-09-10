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
