"use client";

import { Box, Card, CardContent, CardHeader, Typography, Grid, Chip } from "@mui/material";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis } from "recharts";

const COLORS = ["#008080", "#4caf50", "#03a9f4", "#FF8042"];

const accountData = [
  { name: "Intesa Sanpaolo", value: 1200 },
  { name: "Revolut", value: 500 },
  { name: "Contanti", value: 100 },
];

const savingsData = [
  { month: "Gen", amount: 200 },
  { month: "Feb", amount: 150 },
  { month: "Mar", amount: 300 },
  { month: "Apr", amount: 250 },
];

const categoryData = [
  { name: "Supermercato", value: 300 },
  { name: "Affitto", value: 600 },
  { name: "Trasporti", value: 100 },
  { name: "Ristoranti", value: 150 },
];

export default function Analytics() {
  return (
    <Box sx={{ p: { xs: 2, md: 4 } }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" fontWeight="bold" color="primary" gutterBottom>
          Analytics
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Monitora e analizza le tue finanze con Moneo
        </Typography>
      </Box>

      <Grid container spacing={4}>
        {/* FREE CHART */}
        <Grid item xs={12} md={6}>
          <Card sx={{ height: 400 }}>
            <CardHeader title="Spese per Conto (Mese Corrente)" titleTypographyProps={{ variant: "h6", fontWeight: "bold" }} />
            <CardContent sx={{ height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={accountData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    paddingAngle={5}
                    dataKey="value"
                  >
                    {accountData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#fff', borderRadius: '8px', border: '1px solid #eaeaea', color: '#333' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </Grid>

        {/* PREMIUM CHART - BAR */}
        <Grid item xs={12} md={6}>
          <Card sx={{ height: 400, position: 'relative', overflow: 'hidden' }}>
            <Box sx={{ position: 'absolute', top: 16, right: 16, zIndex: 10 }}>
              <Chip label="Premium" color="secondary" size="small" />
            </Box>
            <CardHeader title="Risparmio Mensile nel Tempo" titleTypographyProps={{ variant: "h6", fontWeight: "bold" }} />
            <CardContent sx={{ height: 320, filter: 'blur(4px)', userSelect: 'none' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={savingsData}>
                  <XAxis dataKey="month" stroke="#8884d8" />
                  <YAxis stroke="#8884d8" />
                  <Bar dataKey="amount" fill="#008080" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
            <Box 
              sx={{
                position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                backgroundColor: 'rgba(255,255,255,0.4)', zIndex: 5
              }}
            >
              <Typography variant="h6" color="text.primary" fontWeight="bold">Sblocca con Premium</Typography>
            </Box>
          </Card>
        </Grid>

        {/* PREMIUM CHART - PIE */}
        <Grid item xs={12} md={6}>
          <Card sx={{ height: 400, position: 'relative', overflow: 'hidden' }}>
            <Box sx={{ position: 'absolute', top: 16, right: 16, zIndex: 10 }}>
              <Chip label="Premium" color="secondary" size="small" />
            </Box>
            <CardHeader title="Spese per Categoria" titleTypographyProps={{ variant: "h6", fontWeight: "bold" }} />
            <CardContent sx={{ height: 320, filter: 'blur(4px)', userSelect: 'none' }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={categoryData}
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    dataKey="value"
                  >
                    {categoryData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
            <Box 
              sx={{
                position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                backgroundColor: 'rgba(255,255,255,0.4)', zIndex: 5
              }}
            >
              <Typography variant="h6" color="text.primary" fontWeight="bold">Sblocca con Premium</Typography>
            </Box>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
