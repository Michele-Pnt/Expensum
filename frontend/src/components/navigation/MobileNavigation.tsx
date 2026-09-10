"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Drawer } from "@mui/material";
import { LayoutGrid, Plus } from "lucide-react";

import {
  MOBILE_MORE_ITEMS,
  MOBILE_PRIMARY_ITEMS,
  isNavigationItemActive,
  type NavigationItem,
} from "./navigationConfig";
import styles from "./Navigation.module.css";

const MORE_SHEET_TITLE_ID = "mobile-more-sheet-title";

type MobileNavigationProps = {
  onOpenCapture: () => void;
};

/** Bottom bar persistente su mobile e dentro Telegram, con sheet "Altro". */
export default function MobileNavigation({ onOpenCapture }: MobileNavigationProps) {
  const pathname = usePathname() ?? "";
  const [moreOpen, setMoreOpen] = useState(false);

  const [homeItem, analyticsItem, manageItem] = MOBILE_PRIMARY_ITEMS;

  const isMoreActive = MOBILE_MORE_ITEMS.some((item) => isNavigationItemActive(pathname, item.href));

  const renderPrimaryItem = (item: NavigationItem) => {
    const Icon = item.icon;
    const isActive = isNavigationItemActive(pathname, item.href);
    return (
      <Link
        key={item.id}
        href={item.href}
        className={isActive ? `${styles.mobileItem} ${styles.mobileItemActive}` : styles.mobileItem}
        aria-current={isActive ? "page" : undefined}
      >
        <Icon size={22} strokeWidth={1.75} aria-hidden="true" />
        {item.label}
      </Link>
    );
  };

  return (
    <>
      <nav className={styles.mobileBar} data-tour="primary-navigation" aria-label="Navigazione principale">
        {renderPrimaryItem(homeItem)}
        {renderPrimaryItem(analyticsItem)}

        <button
          type="button"
          className={styles.mobileCapture}
          onClick={onOpenCapture}
          data-action="open-capture"
          data-tour="quick-capture-button"
        >
          <span className={styles.mobileCaptureIcon}>
            <Plus size={24} strokeWidth={2} aria-hidden="true" />
          </span>
          Registra
        </button>

        {renderPrimaryItem(manageItem)}

        <button
          type="button"
          className={isMoreActive ? `${styles.mobileItem} ${styles.mobileItemActive}` : styles.mobileItem}
          onClick={() => setMoreOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={moreOpen}
        >
          <LayoutGrid size={22} strokeWidth={1.75} aria-hidden="true" />
          Altro
        </button>
      </nav>

      <Drawer
        anchor="bottom"
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        slotProps={{
          paper: {
            role: "dialog",
            "aria-modal": true,
            "aria-labelledby": MORE_SHEET_TITLE_ID,
            sx: {
              bgcolor: "var(--color-surface)",
              backgroundImage: "none",
              borderTop: "1px solid var(--color-border)",
              borderTopLeftRadius: 16,
              borderTopRightRadius: 16,
            },
          },
        }}
      >
        <nav className={styles.moreSheet} aria-labelledby={MORE_SHEET_TITLE_ID}>
          <p className={styles.moreTitle} id={MORE_SHEET_TITLE_ID}>Altro</p>
          <div className={styles.moreGrid}>
            {MOBILE_MORE_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = isNavigationItemActive(pathname, item.href);
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className={isActive ? `${styles.moreItem} ${styles.moreItemActive}` : styles.moreItem}
                  aria-current={isActive ? "page" : undefined}
                  // Lo sheet si chiude prima della navigazione, così non resta
                  // aperto sopra la nuova pagina durante la transizione.
                  onClick={() => setMoreOpen(false)}
                >
                  <Icon size={22} strokeWidth={1.75} aria-hidden="true" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </nav>
      </Drawer>
    </>
  );
}
