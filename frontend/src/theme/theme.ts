'use client';
import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'light', // Può essere 'dark' se richiesto in futuro
    primary: {
      main: '#008080', // Verde acqua (Teal)
      light: '#4cb5b5',
      dark: '#005353',
      contrastText: '#ffffff',
    },
    secondary: {
      main: '#4caf50', // Verde
      light: '#80e27e',
      dark: '#087f23',
      contrastText: '#ffffff',
    },
    info: {
      main: '#03a9f4', // Azzurro (Light Blue)
      light: '#67daff',
      dark: '#007ac1',
      contrastText: '#ffffff',
    },
    background: {
      default: '#f5f7fa',
      paper: '#ffffff',
    },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    h1: {
      fontWeight: 700,
    },
    h2: {
      fontWeight: 600,
    },
    h3: {
      fontWeight: 600,
    },
    button: {
      textTransform: 'none', // Disabilita il tutto maiuscolo dei bottoni MUI di default
      fontWeight: 600,
    },
  },
  shape: {
    borderRadius: 12, // Arrotondamento più moderno rispetto ai 4px di base
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: '8px',
          padding: '10px 24px',
          boxShadow: 'none',
          '&:hover': {
            boxShadow: '0px 4px 12px rgba(0, 128, 128, 0.2)', // Effetto hover leggero col verde acqua
          },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: '16px',
          boxShadow: '0px 4px 20px rgba(0, 0, 0, 0.05)',
        },
      },
    },
  },
});

export default theme;
