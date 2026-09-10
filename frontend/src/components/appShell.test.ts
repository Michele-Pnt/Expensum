import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const shellSource = readFileSync(new URL("./ProtectedAppShell.tsx", import.meta.url), "utf8");
const tourSource = readFileSync(new URL("../context/TourContext.tsx", import.meta.url), "utf8");
const spaceSource = readFileSync(new URL("../app/spazio/page.tsx", import.meta.url), "utf8");
const analyticsSource = readFileSync(new URL("../app/analytics/page.tsx", import.meta.url), "utf8");

test("Telegram gets the same responsive shell as the web app", () => {
  // Resta l'autenticazione via init data, sparisce il ramo che rendeva il
  // contenuto senza alcuna navigazione dentro la mini-app.
  assert.match(shellSource, /X-Telegram-Init-Data/);
  assert.doesNotMatch(shellSource, /if \(authStatus\.isTelegram\) \{\s*return/);
});

test("renders exactly one navigation at a time, split at the 900px breakpoint", () => {
  assert.match(shellSource, /useMediaQuery\(theme\.breakpoints\.down\("md"\)\)/);
  assert.match(shellSource, /\{!isMobile && \([\s\S]*?<DesktopNavigation/);
  assert.match(shellSource, /\{isMobile && <MobileNavigation/);
});

test("drops the hamburger, the legacy mobile drawer and the collapsed sidebar state", () => {
  assert.doesNotMatch(shellSource, /desktopOpen|mobileOpen|handleDrawerToggle/);
  assert.doesNotMatch(shellSource, /sidebar-open|MenuIcon/);
  assert.doesNotMatch(shellSource, /from "\.\/Sidebar"/);
});

test("reserves room for the fixed bottom bar and for the desktop rail", () => {
  assert.match(shellSource, /const MOBILE_BAR_HEIGHT = 80;/);
  assert.match(shellSource, /const DESKTOP_RAIL_WIDTH = 220;/);
  assert.match(shellSource, /pb: isMobile \? `calc\(\$\{MOBILE_BAR_HEIGHT\}px \+ env\(safe-area-inset-bottom\)\)`/);
});

test("the tour points at the responsive navigation and no longer opens a hamburger", () => {
  assert.match(tourSource, /selector: '\[data-tour="primary-navigation"\]'/);
  assert.doesNotMatch(tourSource, /data-tour="sidebar-nav"/);
  assert.doesNotMatch(tourSource, /data-action="sidebar-open"/);
  assert.match(tourSource, /barra laterale su computer/);
  assert.match(tourSource, /barra in basso su telefono/);
});

test("the tour steps of the manage area are renamed to Gestisci", () => {
  assert.match(tourSource, /title: "Gestisci: Conti"/);
  assert.match(tourSource, /title: "Gestisci: Categorie"/);
});

test("the manage page is titled Gestisci while its route stays /spazio", () => {
  assert.match(spaceSource, /Gestisci\s*<\/Typography>/);
  assert.match(spaceSource, /aria-label="Sezioni di Gestisci"/);
  assert.doesNotMatch(spaceSource, /Il mio spazio/);
});

test("analytics links to Gestisci and keeps the /spazio route", () => {
  assert.match(analyticsSource, /Apri Gestisci/);
  assert.match(analyticsSource, /href="\/spazio"/);
});
