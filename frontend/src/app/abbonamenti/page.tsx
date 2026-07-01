"use client";

import { useEffect } from "react";
import { Box, Card, CardContent, CardActions, Typography, Grid, Button, List, ListItem, ListItemIcon, ListItemText } from "@mui/material";
import { Check } from "@mui/icons-material";
import { trackPaywallViewed, trackSubscriptionStarted } from "@/lib/analytics";

export default function Abbonamenti() {
  useEffect(() => {
    trackPaywallViewed("abbonamenti_page");
  }, []);

  return (
    <Box sx={{ p: { xs: 2, md: 4 }, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <Box sx={{ mb: 6, textAlign: 'center' }}>
        <Typography variant="h4" fontWeight="bold" color="primary" gutterBottom>
          Scegli il tuo Piano
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Sblocca tutto il potenziale di Moneo con il piano Premium.
        </Typography>
      </Box>

      <Grid container spacing={4} justifyContent="center" maxWidth="md">
        {/* FREE PLAN */}
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', borderRadius: 4 }}>
            <CardContent sx={{ flexGrow: 1, textAlign: 'center', p: 4 }}>
              <Typography variant="h5" fontWeight="bold" gutterBottom>Free</Typography>
              <Typography variant="h3" fontWeight="bold" color="primary" sx={{ my: 2 }}>
                €0<Typography component="span" variant="h6" color="text.secondary">/mese</Typography>
              </Typography>
              <List sx={{ mt: 2 }}>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="primary" /></ListItemIcon>
                  <ListItemText primary="Inserimento spese illimitato via Chat" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="primary" /></ListItemIcon>
                  <ListItemText primary="Grafici mensili base (Spese per Conto)" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="primary" /></ListItemIcon>
                  <ListItemText primary="Scelta tra Avatar Base" />
                </ListItem>
              </List>
            </CardContent>
            <CardActions sx={{ p: 3, pt: 0 }}>
              <Button fullWidth variant="outlined" color="primary" size="large">
                Piano Attuale
              </Button>
            </CardActions>
          </Card>
        </Grid>

        {/* PREMIUM PLAN */}
        <Grid item xs={12} md={6}>
          <Card 
            sx={{
              height: '100%', display: 'flex', flexDirection: 'column', borderRadius: 4,
              border: '2px solid', borderColor: 'primary.main',
              boxShadow: '0px 8px 24px rgba(26, 54, 115, 0.12)'
            }}
          >
            <CardContent sx={{ flexGrow: 1, textAlign: 'center', p: 4 }}>
              <Typography variant="h5" fontWeight="bold" color="secondary" gutterBottom>Premium</Typography>
              <Typography variant="h3" fontWeight="bold" color="secondary" sx={{ my: 2 }}>
                €4.99<Typography component="span" variant="h6" color="text.secondary">/mese</Typography>
              </Typography>
              <List sx={{ mt: 2 }}>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="secondary" /></ListItemIcon>
                  <ListItemText primary="Tutto il piano Free" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="secondary" /></ListItemIcon>
                  <ListItemText primary="Accesso completo ad Analytics Avanzati" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="secondary" /></ListItemIcon>
                  <ListItemText primary="Statistiche Risparmio & Trend Storici" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="secondary" /></ListItemIcon>
                  <ListItemText primary="Assistente AI Proattivo & Alert" />
                </ListItem>
              </List>
            </CardContent>
            <CardActions sx={{ p: 3, pt: 0 }}>
              <Button
                fullWidth
                variant="contained"
                color="secondary"
                size="large"
                onClick={() => trackSubscriptionStarted("pro", "free")}
              >
                Esegui l&apos;upgrade
              </Button>
            </CardActions>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
