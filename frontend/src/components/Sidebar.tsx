"use client";
/* eslint-disable @next/next/no-img-element */

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Drawer, List, ListItem, ListItemButton, ListItemText, Box } from "@mui/material";
import { BarChart2, MessageCircle, CreditCard, MessageSquare, FileText, User, Settings, Gift, Target, Calendar, Landmark } from "lucide-react";
import styles from "./Sidebar.module.css";

const railWidth = 64;
const expandedWidth = 220;

type SidebarProps = {
  mobileOpen?: boolean;
  desktopOpen?: boolean;
  onToggle?: () => void;
  isMobile?: boolean;
};

export default function Sidebar({ mobileOpen = false, desktopOpen = true, onToggle, isMobile = false }: SidebarProps) {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);

  const navItems = [
    { name: "Chat", path: "/chat", icon: <MessageCircle size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Analytics", path: "/analytics", icon: <BarChart2 size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Calendario", path: "/calendario", icon: <Calendar size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Obiettivi", path: "/goals", icon: <Target size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Mutuo", path: "/mutuo", icon: <Landmark size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Report", path: "/reports", icon: <FileText size={20} strokeWidth={1.75} aria-hidden="true" /> },
  ];

  const bottomNavItems = [
    { name: "Il mio Spazio", path: "/spazio", icon: <User size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Feedback", path: "/feedback", icon: <MessageSquare size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Abbonamenti", path: "/abbonamenti", icon: <CreditCard size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Invita amici", path: "/invita", icon: <Gift size={20} strokeWidth={1.75} aria-hidden="true" /> },
    { name: "Impostazioni", path: "/impostazioni", icon: <Settings size={20} strokeWidth={1.75} aria-hidden="true" /> },
  ];

  const renderItems = (items: typeof navItems) =>
    items.map((item) => {
      const isActive = pathname === item.path;
      return (
        <ListItem key={item.path} disablePadding>
          <Link href={item.path} passHref style={{ width: "100%", textDecoration: "none", color: "inherit" }}>
            <ListItemButton
              disableRipple
              aria-label={item.name}
              aria-current={isActive ? "page" : undefined}
              className={isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem}
              onClick={() => {
                if (isMobile && onToggle) onToggle();
              }}
            >
              <span className={styles.navIcon}>{item.icon}</span>
              <ListItemText
                primary={item.name}
                className={styles.navLabel}
                primaryTypographyProps={{ fontWeight: isActive ? 600 : 400, fontSize: "0.9rem" }}
              />
            </ListItemButton>
          </Link>
        </ListItem>
      );
    });

  const drawerContent = (isCollapsedVariant: boolean) => (
    <Box
      className={`${styles.rail} ${isCollapsedVariant && !expanded ? styles.collapsed : ""}`}
      sx={{ width: isCollapsedVariant && !expanded ? railWidth : expandedWidth }}
    >
      <div data-tour="sidebar-nav">
        <div className={styles.brand} onClick={onToggle} style={{ cursor: onToggle ? "pointer" : "default" }}>
          <img src="/logo-expensum-icon.png" alt="Expensum" className={styles.brandLogo} />
          <span className={styles.brandName}>EXPENSUM</span>
        </div>

        <List className={styles.navSection} disablePadding>
          {renderItems(navItems)}
        </List>
      </div>

      <div className={styles.divider} />

      <List className={styles.bottomSection} disablePadding>
        {renderItems(bottomNavItems)}
      </List>
    </Box>
  );

  return (
    <Box component="nav" sx={{ width: { xs: 0, sm: desktopOpen ? railWidth : 0 }, flexShrink: { sm: 0 } }}>
      {/* Mobile drawer: sempre espanso quando aperto, nessun hover su touch */}
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={onToggle}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: "block", sm: "none" },
          "& .MuiDrawer-paper": {
            width: expandedWidth,
            boxSizing: "border-box",
            bgcolor: "var(--color-surface)",
            borderRight: "1px solid var(--color-border)",
            color: "var(--color-text)",
            backgroundImage: "none",
          },
        }}
      >
        {drawerContent(false)}
      </Drawer>

      {/* Desktop: rail fissa a 64px nel layout, si espande a 220px in overlay on-hover */}
      <Drawer
        variant="persistent"
        open={desktopOpen}
        onMouseEnter={() => setExpanded(true)}
        onMouseLeave={() => setExpanded(false)}
        sx={{
          display: { xs: "none", sm: "block" },
          "& .MuiDrawer-paper": {
            position: "fixed",
            width: expanded ? expandedWidth : railWidth,
            boxSizing: "border-box",
            bgcolor: "var(--color-surface)",
            borderRight: "1px solid var(--color-border)",
            color: "var(--color-text)",
            backgroundImage: "none",
            transition: "width 200ms ease",
            zIndex: 1300,
            overflowX: "hidden",
          },
        }}
      >
        {drawerContent(true)}
      </Drawer>
    </Box>
  );
}
