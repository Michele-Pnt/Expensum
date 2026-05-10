'use client';

import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1A3673',
      dark: '#142959',
      light: '#2B4FA8',
      contrastText: '#FFFFFF',
    },
    secondary: {
      main: '#C5A059',
      dark: '#A8853C',
      light: '#D4B47A',
      contrastText: '#FFFFFF',
    },
    background: {
      default: '#F7F6F2',
      paper: '#FFFFFF',
    },
    text: {
      primary: '#1A1A1A',
      secondary: '#6B7280',
    },
    divider: '#E5E2DC',
    error: { main: '#DC2626' },
    success: { main: '#16A34A' },
    info: { main: '#1A3673' },
    warning: { main: '#C5A059' },
  },
  typography: {
    fontFamily: '"Inter", system-ui, sans-serif',
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
          scrollbarColor: '#E5E2DC transparent',
          '&::-webkit-scrollbar': { width: '6px' },
          '&::-webkit-scrollbar-track': { background: 'transparent' },
          '&::-webkit-scrollbar-thumb': {
            background: '#E5E2DC',
            borderRadius: '3px',
            '&:hover': { background: '#B0B5B9' },
          },
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          fontWeight: 600,
          transition: 'transform 150ms ease, box-shadow 150ms ease',
        },
        contained: {
          backgroundColor: '#1A3673',
          color: '#FFFFFF',
          boxShadow: '0 1px 3px rgba(26,54,115,0.20)',
          '&:hover': {
            backgroundColor: '#142959',
            boxShadow: '0 4px 12px rgba(26,54,115,0.30)',
            transform: 'translateY(-1px)',
          },
        },
        outlined: {
          borderColor: '#E5E2DC',
          color: '#1A1A1A',
          '&:hover': {
            borderColor: '#1A3673',
            backgroundColor: 'rgba(26,54,115,0.04)',
          },
        },
        text: {
          color: '#1A1A1A',
          '&:hover': {
            backgroundColor: 'rgba(26,54,115,0.04)',
          },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          background: '#FFFFFF',
          border: '1px solid #E5E2DC',
          boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid #E5E2DC',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: '"Inter", system-ui, sans-serif',
          color: '#6B7280',
          '&.Mui-selected': { color: '#1A3673' },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: { backgroundColor: '#C5A059' },
      },
    },
    MuiSlider: {
      styleOverrides: {
        root: { color: '#1A3673' },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            '& fieldset': { borderColor: '#E5E2DC' },
            '&:hover fieldset': { borderColor: '#B0B5B9' },
            '&.Mui-focused fieldset': { borderColor: '#1A3673' },
          },
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          background: '#1A1A1A',
          border: '1px solid #E5E2DC',
          borderRadius: 8,
          fontSize: '0.8rem',
          color: '#FFFFFF',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          border: '1px solid #E5E2DC',
          backgroundColor: '#F7F6F2',
          color: '#1A1A1A',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          background: '#FFFFFF',
          border: '1px solid #E5E2DC',
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-notchedOutline': { borderColor: '#E5E2DC' },
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: '#F0EDE8' },
        bar: { backgroundColor: '#1A3673' },
      },
    },
  },
});

export default theme;
