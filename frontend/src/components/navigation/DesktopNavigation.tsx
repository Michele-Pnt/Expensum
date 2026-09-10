"use client";
/* eslint-disable @next/next/no-img-element */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus } from "lucide-react";

import {
  NAVIGATION_ITEMS,
  isNavigationItemActive,
  type NavigationGroup,
  type NavigationItem,
} from "./navigationConfig";
import styles from "./Navigation.module.css";

type DesktopNavigationProps = {
  onOpenCapture: () => void;
};

const GROUP_ORDER: readonly NavigationGroup[] = ["primary", "planning", "account"];

/** Sidebar desktop stabile: tutte le destinazioni visibili e raggiungibili con un click. */
export default function DesktopNavigation({ onOpenCapture }: DesktopNavigationProps) {
  const pathname = usePathname() ?? "";

  const renderItem = (item: NavigationItem) => {
    const Icon = item.icon;
    const isActive = isNavigationItemActive(pathname, item.href);
    return (
      <Link
        key={item.id}
        href={item.href}
        className={isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem}
        aria-current={isActive ? "page" : undefined}
      >
        <span className={styles.navIcon}>
          <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
        </span>
        {item.label}
      </Link>
    );
  };

  return (
    <nav className={styles.desktopRail} data-tour="primary-navigation" aria-label="Navigazione principale">
      <div className={styles.brand}>
        <img src="/logo-expensum-icon.png" alt="" className={styles.brandLogo} />
        <span className={styles.brandName}>EXPENSUM</span>
      </div>

      <button
        type="button"
        className={styles.captureButton}
        onClick={onOpenCapture}
        data-action="open-capture"
        data-tour="quick-capture-button"
      >
        <Plus size={20} strokeWidth={2} aria-hidden="true" />
        Registra
      </button>

      <div className={styles.navScroll}>
        {GROUP_ORDER.map((group) => (
          <div key={group} className={styles.navGroup}>
            {NAVIGATION_ITEMS.filter((item) => item.group === group).map(renderItem)}
          </div>
        ))}
      </div>
    </nav>
  );
}
