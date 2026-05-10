"use client";
/* eslint-disable @next/next/no-img-element */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Drawer, List, ListItem, ListItemButton, ListItemText } from "@mui/material";
import { BarChart2, MessageCircle, CreditCard, MessageSquare, Home, FileText } from "lucide-react";
import styles from "./Sidebar.module.css";

const drawerWidth = 240;

export default function Sidebar() {
  const pathname = usePathname();

  const navItems = [
    { name: "Chat", path: "/chat", icon: <MessageCircle size={18} /> },
    { name: "Analytics", path: "/analytics", icon: <BarChart2 size={18} /> },
    { name: "Report", path: "/reports", icon: <FileText size={18} /> },
  ];

  const bottomNavItems = [
    { name: "Feedback", path: "/feedback", icon: <MessageSquare size={18} /> },
    { name: "Abbonamenti", path: "/abbonamenti", icon: <CreditCard size={18} /> },
  ];

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: drawerWidth,
        flexShrink: 0,
        [`& .MuiDrawer-paper`]: {
          width: drawerWidth,
          boxSizing: "border-box",
          bgcolor: "var(--color-surface)",
          borderRight: "1px solid var(--color-border)",
          color: "var(--color-text)",
          backgroundImage: "none",
        },
      }}
    >
      <div className={styles.brand}>
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
    </Drawer>
  );
}
