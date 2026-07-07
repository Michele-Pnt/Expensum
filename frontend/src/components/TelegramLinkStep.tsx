"use client";

import { useEffect, useRef, useState } from "react";
import { Box, Typography, Button, CircularProgress } from "@mui/material";
import { Send as TelegramIcon, CheckCircle2 } from "lucide-react";
import { getCsrfToken } from "@/lib/csrf";

type LinkState = "loading" | "already_linked" | "ready" | "linked" | "error";

export default function TelegramLinkStep() {
  const [state, setState] = useState<LinkState>("loading");
  const [link, setLink] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function requestLink() {
      try {
        const csrfToken = await getCsrfToken();
        const res = await fetch("/api/telegram/link", {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          credentials: "same-origin",
        });
        if (!res.ok) throw new Error("request failed");
        const data = await res.json();
        if (cancelled) return;
        if (data.already_linked) {
          setState("already_linked");
        } else {
          setLink(data.link);
          setState("ready");
        }
      } catch {
        if (!cancelled) setState("error");
      }
    }

    requestLink();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (state !== "ready") return;

    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch("/api/settings", { credentials: "same-origin" });
        if (!res.ok) return;
        const data = await res.json();
        if (data?.account?.telegram_connected) {
          setState("linked");
        }
      } catch {
        // ignora, riprova al prossimo tick
      }
    }, 3000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [state]);

  if (state === "loading") {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
        <CircularProgress size={22} />
      </Box>
    );
  }

  if (state === "already_linked" || state === "linked") {
    return (
      <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, py: 1 }}>
        <CheckCircle2 size={28} color="#2ecc71" />
        <Typography variant="body2" fontWeight={600}>
          Telegram collegato! 🎉
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
          Da ora puoi registrare spese anche scrivendo direttamente al bot su Telegram.
        </Typography>
      </Box>
    );
  }

  if (state === "error") {
    return (
      <Typography variant="body2" color="text.secondary">
        Non è stato possibile generare il link in questo momento. Puoi collegare Telegram più
        tardi dalle Impostazioni.
      </Typography>
    );
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5, py: 0.5 }}>
      <Typography variant="body2" color="text.secondary">
        Collega il tuo account Telegram per registrare spese anche in chat, ovunque ti trovi.
      </Typography>
      <Button
        variant="contained"
        startIcon={<TelegramIcon size={16} />}
        component="a"
        href={link ?? undefined}
        target="_blank"
        rel="noopener noreferrer"
        sx={{
          borderRadius: "8px",
          textTransform: "none",
          background: "linear-gradient(135deg, #6C5CE7, #8b5cf6)",
          "&:hover": { background: "linear-gradient(135deg, #5a4ad1, #7c3aed)" },
        }}
      >
        Apri Telegram e collega
      </Button>
      <Typography variant="caption" color="text.disabled">
        Puoi farlo anche più tardi dalle Impostazioni.
      </Typography>
    </Box>
  );
}
