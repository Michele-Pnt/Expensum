"use client";

import React, { useRef, useEffect } from "react";
import { Box, Button, Container, Grid, Typography, Card, CardContent } from "@mui/material";
import { Security, AutoGraph, AccountBalanceWallet, ChatBubbleOutline } from "@mui/icons-material";
import Link from "next/link";

export default function LandingPage() {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.play().catch(err => console.log("Video autoplay failed:", err));
    }
  }, []);

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Navbar Minimal */}
      <Box sx={{ p: 3, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="h6" color="primary" fontWeight="bold">
          Traky / Moneo
        </Typography>
        <Box gap={2} display="flex">
          <Link href="/chat" passHref>
            <Button variant="outlined" color="primary">Login</Button>
          </Link>
          <Link href="/chat" passHref>
            <Button variant="contained" color="primary">Inizia Gratis</Button>
          </Link>
        </Box>
      </Box>

      {/* Hero Section */}
      <Box sx={{ flexGrow: 1, display: "flex", alignItems: "center", py: 10, bgcolor: "background.default" }}>
        <Container maxWidth="lg">
          <Grid container spacing={6} alignItems="center">
            <Grid item xs={12} md={6}>
              <Typography variant="h1" sx={{ fontSize: { xs: "3rem", md: "4rem" }, mb: 2, color: "#111" }}>
                Gestisci le tue finanze con l'<Box component="span" sx={{ color: "primary.main" }}>Intelligenza Artificiale</Box>.
              </Typography>
              <Typography variant="h6" color="text.secondary" sx={{ mb: 4, fontWeight: 400, lineHeight: 1.6 }}>
                Traky e Moneo si uniscono per offrirti l'assistente finanziario definitivo. Tieni traccia delle spese, ottimizza i tuoi abbonamenti e ricevi consigli personalizzati in tempo reale.
              </Typography>
              <Box display="flex" gap={2}>
                <Link href="/chat" passHref>
                  <Button variant="contained" color="secondary" size="large" sx={{ px: 4, py: 1.5, fontSize: "1.1rem" }}>
                    Parla con Moneo
                  </Button>
                </Link>
                <Link href="/analytics" passHref>
                  <Button variant="outlined" color="primary" size="large" sx={{ px: 4, py: 1.5, fontSize: "1.1rem" }}>
                    Vedi Demo
                  </Button>
                </Link>
              </Box>
            </Grid>
            <Grid item xs={12} md={6}>
              {/* Placeholder for Hero Image/Video */}
              <Box 
                sx={{ 
                  width: "100%", 
                  height: 400, 
                  bgcolor: "#e0f2f1", 
                  borderRadius: 4,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  boxShadow: "0px 20px 40px rgba(0, 128, 128, 0.15)"
                }}
              >
                <video
                  ref={videoRef}
                  autoPlay
                  loop
                  muted
                  playsInline
                  style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "16px" }}
                >
                  <source src="/AvatarMoneoV2.mp4?v=2" type="video/mp4" />
                </video>
              </Box>
            </Grid>
          </Grid>
        </Container>
      </Box>

      {/* Trust Signals */}
      <Box sx={{ py: 6, bgcolor: "#fff", borderTop: "1px solid #eaeaea", borderBottom: "1px solid #eaeaea" }}>
        <Container maxWidth="lg">
          <Grid container spacing={4} justifyContent="center" textAlign="center">
            <Grid item xs={12}>
              <Typography variant="subtitle1" color="text.secondary" sx={{ mb: 3 }}>
                DATI AL SICURO, SINCRONIZZAZIONE PERFETTA
              </Typography>
            </Grid>
            <Grid item xs={6} md={3}>
              <Box display="flex" flexDirection="column" alignItems="center">
                <Security color="primary" sx={{ fontSize: 40, mb: 1 }} />
                <Typography variant="body1" fontWeight="bold">Privacy First</Typography>
              </Box>
            </Grid>
            <Grid item xs={6} md={3}>
              <Box display="flex" flexDirection="column" alignItems="center">
                <Typography variant="h5" fontWeight="bold" color="text.secondary" sx={{ mb: 1 }}>N</Typography>
                <Typography variant="body1" fontWeight="bold">Sincronizzato con Notion</Typography>
              </Box>
            </Grid>
          </Grid>
        </Container>
      </Box>

      {/* Features Section */}
      <Container maxWidth="lg" sx={{ py: 10 }}>
        <Typography variant="h3" textAlign="center" sx={{ mb: 8 }}>
          Come Traky può aiutarti
        </Typography>
        <Grid container spacing={4}>
          <Grid item xs={12} md={4}>
            <Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <CardContent sx={{ flexGrow: 1, p: 4 }}>
                <ChatBubbleOutline color="primary" sx={{ fontSize: 48, mb: 2 }} />
                <Typography variant="h5" sx={{ mb: 2, fontWeight: "bold" }}>Assistente Chatbot</Typography>
                <Typography color="text.secondary">
                  Aggiungi le tue spese semplicemente parlando o scrivendo a Moneo su Telegram o sulla Web App. Non c'è bisogno di form noiosi.
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <CardContent sx={{ flexGrow: 1, p: 4 }}>
                <AutoGraph color="secondary" sx={{ fontSize: 48, mb: 2 }} />
                <Typography variant="h5" sx={{ mb: 2, fontWeight: "bold" }}>Analytics Avanzati</Typography>
                <Typography color="text.secondary">
                  Visualizza l'andamento delle tue spese con grafici chiari e intuitivi. Scopri dove stai spendendo di più e come risparmiare.
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <CardContent sx={{ flexGrow: 1, p: 4 }}>
                <AccountBalanceWallet color="info" sx={{ fontSize: 48, mb: 2 }} />
                <Typography variant="h5" sx={{ mb: 2, fontWeight: "bold" }}>Gestione Abbonamenti</Typography>
                <Typography color="text.secondary">
                  Tieni traccia di tutte le tue iscrizioni (Netflix, Palestra, Spotify) e ricevi notifiche prima che ti vengano addebitate.
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>

      {/* Footer */}
      <Box sx={{ bgcolor: "#111", color: "#fff", py: 6, mt: "auto" }}>
        <Container maxWidth="lg">
          <Typography variant="body2" textAlign="center">
            © {new Date().getFullYear()} Finance-Agents / Traky. Tutti i diritti riservati.
          </Typography>
        </Container>
      </Box>
    </Box>
  );
}
