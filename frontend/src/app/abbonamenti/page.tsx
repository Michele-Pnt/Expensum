"use client";

import { useEffect } from "react";
import { Box, Card, CardContent, CardActions, Typography, Grid, Button, List, ListItem, ListItemIcon, ListItemText, Chip } from "@mui/material";
import { Check, WorkspacePremium } from "@mui/icons-material";
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

      <Grid container spacing={4} justifyContent="center" maxWidth="lg">
        {/* FREE PLAN */}
        <Grid item xs={12} md={4}>
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
        <Grid item xs={12} md={4}>
          <Card
            sx={{
              height: '100%', display: 'flex', flexDirection: 'column', borderRadius: 4,
              border: '2px solid', borderColor: 'divider',
              opacity: 0.85,
            }}
          >
            <CardContent sx={{ flexGrow: 1, textAlign: 'center', p: 4 }}>
              <Typography variant="h5" fontWeight="bold" color="secondary" gutterBottom>Premium</Typography>
              <Box
                sx={{
                  my: 2,
                  position: 'relative',
                  display: 'inline-flex',
                  alignItems: 'baseline',
                }}
              >
                <Typography
                  variant="h3"
                  fontWeight="bold"
                  color="secondary"
                  sx={{
                    filter: 'blur(7px)',
                    userSelect: 'none',
                  }}
                  aria-hidden="true"
                >
                  €4.99<Typography component="span" variant="h6" color="text.secondary">/mese</Typography>
                </Typography>
                <Chip
                  label="Prossimamente"
                  size="small"
                  color="secondary"
                  variant="outlined"
                  sx={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                  }}
                />
              </Box>
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
              <Button fullWidth variant="outlined" color="secondary" size="large" disabled>
                Non ancora disponibile
              </Button>
            </CardActions>
          </Card>
        </Grid>

        {/* LIFETIME FOUNDER PLAN */}
        <Grid item xs={12} md={4}>
          <Card
            sx={{
              height: '100%', display: 'flex', flexDirection: 'column', borderRadius: 4,
              border: '2px solid', borderColor: 'primary.main',
              boxShadow: '0px 8px 24px rgba(26, 54, 115, 0.12)',
              position: 'relative',
              overflow: 'visible',
            }}
          >
            <Chip
              icon={<WorkspacePremium sx={{ color: '#fff !important' }} />}
              label="Offerta di lancio"
              color="primary"
              sx={{
                position: 'absolute',
                top: -16,
                left: '50%',
                transform: 'translateX(-50%)',
                fontWeight: 600,
                color: '#fff',
              }}
            />
            <CardContent sx={{ flexGrow: 1, textAlign: 'center', p: 4, pt: 5 }}>
              <Typography variant="h5" fontWeight="bold" color="primary" gutterBottom>Lifetime Founder</Typography>
              <Typography variant="h3" fontWeight="bold" color="primary" sx={{ my: 2 }}>
                €89<Typography component="span" variant="h6" color="text.secondary"> una tantum</Typography>
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Posti limitati — solo per i primi utenti
              </Typography>
              <List sx={{ mt: 2 }}>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="primary" /></ListItemIcon>
                  <ListItemText primary="Premium sbloccato per sempre" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="primary" /></ListItemIcon>
                  <ListItemText primary="Nessun costo ricorrente, mai" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="primary" /></ListItemIcon>
                  <ListItemText primary="Badge Founder esclusivo" />
                </ListItem>
                <ListItem disablePadding sx={{ mb: 1 }}>
                  <ListItemIcon sx={{ minWidth: 36 }}><Check color="primary" /></ListItemIcon>
                  <ListItemText primary="Accesso prioritario alle nuove feature" />
                </ListItem>
              </List>
            </CardContent>
            <CardActions sx={{ p: 3, pt: 0 }}>
              <Button
                fullWidth
                variant="contained"
                color="primary"
                size="large"
                onClick={() => trackSubscriptionStarted("lifetime_founder", "free")}
              >
                Diventa Founder
              </Button>
            </CardActions>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
