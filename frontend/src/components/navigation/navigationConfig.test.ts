import assert from "node:assert/strict";
import test from "node:test";

import {
  MOBILE_MORE_ITEMS,
  MOBILE_PRIMARY_ITEMS,
  NAVIGATION_ITEMS,
  isNavigationItemActive,
} from "./navigationConfig";

test("desktop navigation exposes every destination in the approved order", () => {
  assert.deepEqual(
    NAVIGATION_ITEMS.map((item) => item.id),
    [
      "home",
      "analytics",
      "manage",
      "chat",
      "calendar",
      "goals",
      "mortgage",
      "reports",
      "feedback",
      "plan",
      "invite",
      "settings",
    ],
  );
});

test("renames My Space to Gestisci without changing its route", () => {
  const manage = NAVIGATION_ITEMS.find((item) => item.id === "manage");
  assert.ok(manage);
  assert.equal(manage.label, "Gestisci");
  assert.equal(manage.href, "/spazio");
});

test("renames the subscription entry to Il tuo piano without changing its route", () => {
  const plan = NAVIGATION_ITEMS.find((item) => item.id === "plan");
  assert.ok(plan);
  assert.equal(plan.label, "Il tuo piano");
  assert.equal(plan.href, "/abbonamenti");
});

test("labels and routes match the approved navigation model", () => {
  assert.deepEqual(
    NAVIGATION_ITEMS.map((item) => [item.label, item.href]),
    [
      ["Home", "/home"],
      ["Analytics", "/analytics"],
      ["Gestisci", "/spazio"],
      ["Chat", "/chat"],
      ["Calendario", "/calendario"],
      ["Obiettivi", "/goals"],
      ["Mutuo", "/mutuo"],
      ["Report", "/reports"],
      ["Feedback", "/feedback"],
      ["Il tuo piano", "/abbonamenti"],
      ["Invita amici", "/invita"],
      ["Impostazioni", "/impostazioni"],
    ],
  );
});

test("assigns every item to a navigation group", () => {
  const groups = new Map(NAVIGATION_ITEMS.map((item) => [item.id, item.group]));
  assert.equal(groups.get("home"), "primary");
  assert.equal(groups.get("analytics"), "primary");
  assert.equal(groups.get("chat"), "planning");
  assert.equal(groups.get("manage"), "primary");
  assert.equal(groups.get("calendar"), "planning");
  assert.equal(groups.get("goals"), "planning");
  assert.equal(groups.get("mortgage"), "planning");
  assert.equal(groups.get("reports"), "planning");
  assert.equal(groups.get("feedback"), "account");
  assert.equal(groups.get("plan"), "account");
  assert.equal(groups.get("invite"), "account");
  assert.equal(groups.get("settings"), "account");
});

test("every item exposes an icon component", () => {
  for (const item of NAVIGATION_ITEMS) {
    assert.ok(item.icon, `icona mancante per ${item.id}`);
    assert.ok(
      ["function", "object"].includes(typeof item.icon),
      `icona non renderizzabile per ${item.id}`,
    );
  }
});

test("home is the entry point of the app", () => {
  const home = NAVIGATION_ITEMS.find((item) => item.id === "home");
  assert.ok(home);
  assert.equal(home.href, "/home");
  assert.equal(NAVIGATION_ITEMS[0].id, "home");
});

test("marks the exact route as active", () => {
  assert.equal(isNavigationItemActive("/chat", "/chat"), true);
  assert.equal(isNavigationItemActive("/analytics", "/chat"), false);
});

test("marks nested routes as active for their parent entry", () => {
  assert.equal(isNavigationItemActive("/impostazioni/privacy", "/impostazioni"), true);
  assert.equal(isNavigationItemActive("/reports/abc123token", "/reports"), true);
  assert.equal(isNavigationItemActive("/spazio?tab=transfers", "/spazio"), true);
});

test("does not treat a route sharing only a prefix as active", () => {
  assert.equal(isNavigationItemActive("/abbonamenti-legacy", "/abbonamenti"), false);
  assert.equal(isNavigationItemActive("/goals-archive", "/goals"), false);
});

test("mobile primary bar keeps Home, Analytics and Gestisci reachable with one tap", () => {
  assert.deepEqual(
    MOBILE_PRIMARY_ITEMS.map((item) => item.id),
    ["home", "analytics", "manage"],
  );
});

test("mobile More sheet holds every remaining destination", () => {
  assert.deepEqual(
    MOBILE_MORE_ITEMS.map((item) => item.id),
    ["chat", "calendar", "goals", "mortgage", "reports", "feedback", "plan", "invite", "settings"],
  );
});
