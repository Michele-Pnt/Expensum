"use client";
/* eslint-disable @next/next/no-img-element */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Drawer, List, ListItem, ListItemButton, ListItemText, Box } from "@mui/material";
import { BarChart2, MessageCircle, CreditCard, MessageSquare, FileText, User, Settings, Gift } from "lucide-react";
import styles from "./Sidebar.module.css";

const drawerWidth = 240;

type SidebarProps = {
  mobileOpen?: boolean;
  desktopOpen?: boolean;
  onToggle?: () => void;
  isMobile?: boolean;
};

export default function Sidebar({ mobileOpen = false, desktopOpen = true, onToggle, isMobile = false }: SidebarProps) {
  const pathname = usePathname();

  const navItems = [
    { name: "Chat", path: "/chat", icon: <MessageCircle size={18} /> },
    { name: "Analytics", path: "/analytics", icon: <BarChart2 size={18} /> },
    { name: "Report", path: "/reports", icon: <FileText size={18} /> },
    { name: "Il mio Spazio", path: "/spazio", icon: <User size={18} /> },
  ];

  const bottomNavItems = [
    { name: "Feedback", path: "/feedback", icon: <MessageSquare size={18} /> },
    { name: "Abbonamenti", path: "/abbonamenti", icon: <CreditCard size={18} /> },
    { name: "Invita amici", path: "/invita", icon: <Gift size={18} /> },
    { name: "Impostazioni", path: "/impostazioni", icon: <Settings size={18} /> },
  ];

  const drawerContent = (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div data-tour="sidebar-nav">
        <div className={styles.brand} onClick={onToggle} style={{ cursor: onToggle ? "pointer" : "default" }}>
          <img src="/logo-expensum-icon.png" alt="Expensum" className={styles.brandLogo} />
          <span className={styles.brandName}>EXPENSUM</span>
        </div>

        <List className={styles.navSection} disablePadding>
        {navItems.map((item) => {
          const isActive = pathname === item.path;
          return (
            <ListItem key={item.path} disablePadding>
              <Link href={item.path} passHref style={{ width: "100%", textDecoration: "none", color: "inherit" }}>
                <ListItemButton
                  disableRipple
                  className={isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem}
                  onClick={() => {
                    if (isMobile && onToggle) {
                      onToggle();
                    }
                  }}
                >
                  <span className={styles.navIcon}>{item.icon}</span>
                  <ListItemText
                    primary={item.name}
                    primaryTypographyProps={{ fontWeight: isActive ? 600 : 400, fontSize: "0.9rem" }}
                  />
                </ListItemButton>
              </Link>
            </ListItem>
          );
        })}
        </List>
      </div>

      <div className={styles.divider} />

      <List className={styles.bottomSection} disablePadding>
        {bottomNavItems.map((item) => {
          const isActive = pathname === item.path;
          return (
            <ListItem key={item.path} disablePadding>
              <Link href={item.path} passHref style={{ width: "100%", textDecoration: "none", color: "inherit" }}>
                <ListItemButton
                  disableRipple
                  className={isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem}
                  onClick={() => {
                    if (isMobile && onToggle) {
                      onToggle();
                    }
                  }}
                >
                  <span className={styles.navIcon}>{item.icon}</span>
                  <ListItemText
                    primary={item.name}
                    primaryTypographyProps={{ fontWeight: isActive ? 600 : 400, fontSize: "0.9rem" }}
                  />
                </ListItemButton>
              </Link>
            </ListItem>
          );
        })}
      </List>
    </Box>
  );

  return (
    <Box component="nav" sx={{ width: { xs: 0, sm: desktopOpen ? drawerWidth : 0 }, flexShrink: { sm: 0 } }}>
      {/* Mobile drawer */}
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={onToggle}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: "block", sm: "none" },
          "& .MuiDrawer-paper": {
            width: drawerWidth,
            boxSizing: "border-box",
            bgcolor: "var(--color-surface)",
            borderRight: "1px solid var(--color-border)",
            color: "var(--color-text)",
            backgroundImage: "none",
          },
        }}
      >
        {drawerContent}
      </Drawer>

      {/* Desktop drawer */}
      <Drawer
        variant="persistent"
        open={desktopOpen}
        sx={{
          display: { xs: "none", sm: "block" },
          "& .MuiDrawer-paper": {
            width: drawerWidth,
            boxSizing: "border-box",
            bgcolor: "var(--color-surface)",
            borderRight: "1px solid var(--color-border)",
            color: "var(--color-text)",
            backgroundImage: "none",
          },
        }}
      >
        {drawerContent}
      </Drawer>
    </Box>
  );
}
