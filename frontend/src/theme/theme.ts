'use client';

import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#5FC4CB',
      dark: '#4AA7AE',
      light: '#7ED0D6',
      contrastText: '#1C363D',
    },
    secondary: {
      main: '#B0B5B9',
      dark: '#8D9296',
      light: '#C7CBCE',
      contrastText: '#1C363D',
    },
    background: {
      default: '#1C363D',
      paper: '#1C363D',
    },
    text: {
      primary: '#E9F1EA',
      secondary: '#B0B5B9',
    },
    divider: 'rgba(176,181,185,0.25)',
    error: { main: '#DC2626' },
    success: { main: '#16A34A' },
    info: { main: '#5FC4CB' },
    warning: { main: '#F0A93E' },
  },
  typography: {
    fontFamily: '"Sora", system-ui, sans-serif',
    // Titoli in Sora Light col letter-spacing aumentato (vedi
    // foundations-typography.html sul design system): non il bold di default
    // di MUI. h4/h5/h6 restano medium/semibold, sono titoli di card/sezione
    // piu' piccoli dove il peso leggero perderebbe leggibilita'.
    h1: { fontWeight: 300, letterSpacing: '0.01em' },
    h2: { fontWeight: 300, letterSpacing: '0.015em' },
    h3: { fontWeight: 500 },
    h4: { fontWeight: 500 },
    h5: { fontWeight: 500 },
    h6: { fontWeight: 600 },
    button: {
      textTransform: 'none',
      fontWeight: 600,
      letterSpacing: '0.01em',
    },
  },
  shape: { borderRadius: 12 },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundImage: 'none',
          scrollbarColor: 'rgba(176,181,185,0.25) transparent',
          '&::-webkit-scrollbar': { width: '6px' },
          '&::-webkit-scrollbar-track': { background: 'transparent' },
          '&::-webkit-scrollbar-thumb': {
            background: 'rgba(176,181,185,0.25)',
            borderRadius: '3px',
            '&:hover': { background: '#B0B5B9' },
          },
        },
        // Recharts focalizza internamente questo layer SVG quando si seleziona un dato.
        // Il valore resta disponibile nel tooltip: rimuoviamo solo il ring nativo di Chrome.
        '.recharts-surface g[tabindex="-1"]:focus': {
          outline: 'none',
        },
      },
    },
    MuiButtonBase: {
      styleOverrides: {
        root: {
          '&.Mui-focusVisible': {
            outline: '2px solid #5FC4CB',
            outlineOffset: '2px',
          },
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          fontWeight: 600,
          minHeight: 44,
          transition: 'background-color 150ms ease, border-color 150ms ease',
        },
        contained: {
          backgroundColor: '#5FC4CB',
          color: '#1C363D',
          boxShadow: 'none',
          '&:hover': {
            backgroundColor: '#7ED0D6',
            boxShadow: 'none',
          },
        },
        outlined: {
          borderColor: 'rgba(176,181,185,0.25)',
          color: '#E9F1EA',
          '&:hover': {
            borderColor: '#B0B5B9',
            backgroundColor: 'rgba(233,241,234,0.04)',
          },
        },
        text: {
          color: '#E9F1EA',
          '&:hover': {
            backgroundColor: 'rgba(233,241,234,0.04)',
          },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          background: 'rgba(233,241,234,0.04)',
          border: '1px solid rgba(176,181,185,0.25)',
          boxShadow: 'none',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#1C363D',
          border: '1px solid rgba(176,181,185,0.25)',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: '"Sora", system-ui, sans-serif',
          color: '#B0B5B9',
          minHeight: 44,
          '&.Mui-selected': { color: '#5FC4CB' },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: { backgroundColor: '#5FC4CB' },
      },
    },
    MuiSlider: {
      styleOverrides: {
        root: { color: '#5FC4CB' },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            '& fieldset': { borderColor: 'rgba(176,181,185,0.25)' },
            '&:hover fieldset': { borderColor: '#B0B5B9' },
            '&.Mui-focused fieldset': { borderColor: '#5FC4CB' },
          },
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          background: '#1C363D',
          border: '1px solid rgba(176,181,185,0.25)',
          borderRadius: 8,
          fontSize: '0.8rem',
          color: '#E9F1EA',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          border: '1px solid rgba(176,181,185,0.25)',
          backgroundColor: 'rgba(233,241,234,0.04)',
          color: '#E9F1EA',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          background: '#1C363D',
          border: '1px solid rgba(176,181,185,0.25)',
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(176,181,185,0.25)' },
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: 'rgba(176,181,185,0.18)' },
        bar: { backgroundColor: '#5FC4CB' },
      },
    },
  },
});

export default theme;
