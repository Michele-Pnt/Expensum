"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Badge,
  Box,
  Button,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Popover,
  Typography,
} from "@mui/material";
import { Bell } from "lucide-react";
import { apiFetch } from "@/lib/api";

type Notification = {
  id: number;
  type: string;
  title: string;
  body: string;
  payload: Record<string, unknown> | null;
  priority: "info" | "warning" | "critical";
  read: boolean;
  created_at: string | null;
};

const POLL_INTERVAL_MS = 60_000;

/**
 * Campanella notifiche in-app: eventi asincroni indipendenti dalla sessione
 * dell'utente (report periodici, budget, addebiti ricorrenti, inattività,
 * anomalie di sicurezza, messaggi admin) — vedi src/notification_service.py.
 */
export default function NotificationBell() {
  const [anchorEl, setAnchorEl] = useState<HTMLButtonElement | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);
  const isOpen = Boolean(anchorEl);

  const fetchUnreadCount = useCallback(async () => {
    try {
      const data = await apiFetch<{ unread_count: number }>("/api/notifications/unread-count");
      setUnreadCount(data.unread_count ?? 0);
    } catch {
      // best-effort: il badge resta invariato se la richiesta fallisce
    }
  }, []);

  useEffect(() => {
    fetchUnreadCount();
    const interval = setInterval(fetchUnreadCount, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchUnreadCount]);

  const openPanel = useCallback(async (event: React.MouseEvent<HTMLButtonElement>) => {
    setAnchorEl(event.currentTarget);
    setLoading(true);
    try {
      const data = await apiFetch<{ notifications: Notification[] }>("/api/notifications");
      setNotifications(data.notifications ?? []);
    } catch {
      // best-effort: il pannello resta con l'ultima lista nota
    } finally {
      setLoading(false);
    }
  }, []);

  const closePanel = useCallback(() => setAnchorEl(null), []);

  const markRead = useCallback(async (notification: Notification) => {
    if (notification.read) return;
    setNotifications((prev) =>
      prev.map((n) => (n.id === notification.id ? { ...n, read: true } : n))
    );
    setUnreadCount((prev) => Math.max(0, prev - 1));
    try {
      await apiFetch(`/api/notifications/${notification.id}/read`, { method: "POST" });
    } catch {
      // best-effort: allo scroll successivo la lista si riallinea comunque
    }
  }, []);

  const markAllRead = useCallback(async () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    setUnreadCount(0);
    try {
      await apiFetch("/api/notifications/read-all", { method: "POST" });
    } catch {
      // best-effort: alla prossima apertura il pannello si riallinea comunque
    }
  }, []);

  return (
    <>
      <IconButton
        aria-label="Notifiche"
        aria-haspopup="dialog"
        onClick={openPanel}
        sx={{ width: 44, height: 44 }}
      >
        <Badge badgeContent={unreadCount} color="error" max={99}>
          <Bell size={20} strokeWidth={1.75} aria-hidden="true" />
        </Badge>
      </IconButton>
      <Popover
        open={isOpen}
        anchorEl={anchorEl}
        onClose={closePanel}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{ paper: { sx: { width: 360, maxHeight: 420 } } }}
      >
        <Box sx={{ p: 2, pb: 1, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Typography variant="subtitle2">Notifiche</Typography>
          {unreadCount > 0 && (
            <Button size="small" onClick={markAllRead}>
              Segna tutte come lette
            </Button>
          )}
        </Box>
        {loading ? (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="text.secondary">Caricamento…</Typography>
          </Box>
        ) : notifications.length === 0 ? (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="text.secondary">Nessuna notifica.</Typography>
          </Box>
        ) : (
          <List dense disablePadding sx={{ overflowY: "auto" }}>
            {notifications.map((notification) => (
              <ListItemButton
                key={notification.id}
                onClick={() => markRead(notification)}
                sx={{
                  alignItems: "flex-start",
                  bgcolor: notification.read ? "transparent" : "action.hover",
                }}
              >
                <ListItemText
                  primary={notification.title}
                  secondary={notification.body}
                  slotProps={{
                    primary: { variant: "body2", fontWeight: notification.read ? 400 : 600 },
                    secondary: { variant: "body2", color: "text.secondary" },
                  }}
                />
              </ListItemButton>
            ))}
          </List>
        )}
      </Popover>
    </>
  );
}
