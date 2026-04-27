"use client";

import { useState, useRef, useEffect } from "react";
import { Box, Paper, Typography, TextField, IconButton, InputAdornment } from "@mui/material";
import { Send, Image as ImageIcon, Mic, VideoCall } from "@mui/icons-material";

export default function ChatMiniApp() {
  const [inputText, setInputText] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.play().catch(err => console.log("Video autoplay failed:", err));
    }
  }, []);

  const chatHistory = [
    { id: 1, sender: "bot", text: "Ciao! Sono Moneo. Come posso aiutarti oggi con le tue finanze?" },
    { id: 2, sender: "user", text: "Ho speso 24 euro per il sushi." },
    { id: 3, sender: "bot", text: "Oh, sushi! Ottima scelta. Ho registrato €24.00 nella categoria 'Ristoranti'. C'è altro?" },
  ];

  const handleSend = () => {
    if (!inputText.trim()) return;
    console.log("Inviato:", inputText);
    setInputText("");
  };

  return (
    <Box sx={{ height: "100vh", display: "flex", flexDirection: "column", bgcolor: "background.default" }}>
      {/* Video Avatar Section */}
      <Box 
        sx={{ 
          width: "100%", height: "35vh", bgcolor: "#111", 
          display: "flex", alignItems: "center", justifyContent: "center",
          borderBottom: "1px solid #333", overflow: "hidden", position: "relative"
        }}
      >
        <video
          ref={videoRef}
          autoPlay
          loop
          muted
          playsInline
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        >
          <source src="/AvatarMoneoV2.mp4?v=2" type="video/mp4" />
        </video>
        <Box sx={{ position: "absolute", bottom: 16, left: 16, display: "flex", alignItems: "center", gap: 1 }}>
          <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: "#4caf50" }} />
          <Typography variant="caption" color="#fff" fontWeight="bold">Moneo Online</Typography>
        </Box>
      </Box>

      {/* Chat Messages */}
      <Box sx={{ flexGrow: 1, overflowY: "auto", p: 2, display: "flex", flexDirection: "column", gap: 2 }}>
        {chatHistory.map((msg) => (
          <Box 
            key={msg.id} 
            sx={{ 
              display: "flex", 
              justifyContent: msg.sender === "user" ? "flex-end" : "flex-start" 
            }}
          >
            <Paper 
              elevation={0}
              sx={{ 
                p: 1.5, px: 2, maxWidth: "80%",
                bgcolor: msg.sender === "user" ? "primary.main" : "#fff",
                color: msg.sender === "user" ? "#fff" : "text.primary",
                borderRadius: msg.sender === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                border: msg.sender === "user" ? "none" : "1px solid #eaeaea",
                boxShadow: "0 2px 5px rgba(0,0,0,0.05)"
              }}
            >
              <Typography variant="body1">{msg.text}</Typography>
            </Paper>
          </Box>
        ))}
      </Box>

      {/* Input Area */}
      <Box sx={{ p: 2, bgcolor: "#fff", borderTop: "1px solid #eaeaea", display: "flex", alignItems: "center", gap: 1 }}>
        <IconButton color="primary" size="small"><ImageIcon /></IconButton>
        <IconButton color="primary" size="small"><Mic /></IconButton>
        <IconButton color="primary" size="small"><VideoCall /></IconButton>
        
        <TextField 
          fullWidth
          variant="outlined"
          size="small"
          placeholder="Scrivi un messaggio..."
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          sx={{
            "& .MuiOutlinedInput-root": {
              borderRadius: 20,
              bgcolor: "#f5f7fa"
            }
          }}
          InputProps={{
            endAdornment: (
              <InputAdornment position="end">
                <IconButton color="primary" onClick={handleSend} edge="end">
                  <Send />
                </IconButton>
              </InputAdornment>
            )
          }}
        />
      </Box>
    </Box>
  );
}
