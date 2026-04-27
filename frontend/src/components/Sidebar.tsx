"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Box, Drawer, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Typography } from "@mui/material";
import { ChatBubbleOutline, BarChart, CreditCard, Feedback, AccountBalanceWallet } from "@mui/icons-material";

const drawerWidth = 240;

export default function Sidebar() {
  const pathname = usePathname();

  const navItems = [
    { name: "Home (Landing)", path: "/", icon: <ChatBubbleOutline /> },
    { name: "Chat (Moneo)", path: "/chat", icon: <ChatBubbleOutline /> },
    { name: "Analytics", path: "/analytics", icon: <BarChart /> },
  ];

  const bottomNavItems = [
    { name: "Feedback", path: "/feedback", icon: <Feedback /> },
    { name: "Abbonamenti", path: "/abbonamenti", icon: <CreditCard /> },
  ];

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: drawerWidth,
        flexShrink: 0,
        [`& .MuiDrawer-paper`]: { width: drawerWidth, boxSizing: "border-box", bgcolor: "#1e293b", color: "#fff" },
      }}
    >
      <Box sx={{ p: 3, display: "flex", alignItems: "center", gap: 1 }}>
        <AccountBalanceWallet sx={{ color: "#008080" }} />
        <Typography variant="h6" fontWeight="bold" color="white">
          Traky / Moneo
        </Typography>
      </Box>

      <List sx={{ px: 2, flexGrow: 1 }}>
        {navItems.map((item) => {
          const isActive = pathname === item.path;
          return (
            <ListItem key={item.path} disablePadding sx={{ mb: 1 }}>
              <Link href={item.path} passHref style={{ width: '100%', textDecoration: 'none', color: 'inherit' }}>
                <ListItemButton 
                  sx={{ 
                    borderRadius: 2, 
                    bgcolor: isActive ? 'rgba(0, 128, 128, 0.2)' : 'transparent',
                    color: isActive ? '#008080' : '#cbd5e1',
                    '&:hover': { bgcolor: 'rgba(0, 128, 128, 0.1)' }
                  }}
                >
                  <ListItemIcon sx={{ color: isActive ? '#008080' : '#cbd5e1', minWidth: 40 }}>
                    {item.icon}
                  </ListItemIcon>
                  <ListItemText primary={item.name} primaryTypographyProps={{ fontWeight: isActive ? 600 : 400 }} />
                </ListItemButton>
              </Link>
            </ListItem>
          );
        })}
      </List>

      <List sx={{ px: 2, mb: 2 }}>
        {bottomNavItems.map((item) => {
          const isActive = pathname === item.path;
          return (
            <ListItem key={item.path} disablePadding sx={{ mb: 1 }}>
              <Link href={item.path} passHref style={{ width: '100%', textDecoration: 'none', color: 'inherit' }}>
                <ListItemButton 
                  sx={{ 
                    borderRadius: 2, 
                    bgcolor: isActive ? 'rgba(0, 128, 128, 0.2)' : 'transparent',
                    color: isActive ? '#008080' : '#cbd5e1',
                    '&:hover': { bgcolor: 'rgba(0, 128, 128, 0.1)' }
                  }}
                >
                  <ListItemIcon sx={{ color: isActive ? '#008080' : '#cbd5e1', minWidth: 40 }}>
                    {item.icon}
                  </ListItemIcon>
                  <ListItemText primary={item.name} primaryTypographyProps={{ fontWeight: isActive ? 600 : 400 }} />
                </ListItemButton>
              </Link>
            </ListItem>
          );
        })}
      </List>
    </Drawer>
  );
}
