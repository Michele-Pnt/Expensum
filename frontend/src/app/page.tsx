"use client";

import { useState } from "react";
import { Send, Image as ImageIcon, Mic, Video } from "lucide-react";
import styles from "./page.module.css";

export default function Home() {
  const [inputText, setInputText] = useState("");

  const chatHistory = [
    { id: 1, sender: "bot", text: "Ciao! Sono Moneo. Come posso aiutarti oggi con le tue finanze?" },
    { id: 2, sender: "user", text: "Ho speso 24 euro per il sushi." },
    { id: 3, sender: "bot", text: "Oh, sushi! Ottima scelta. Ho registrato €24.00 nella categoria 'Ristoranti'. C'è altro?" },
  ];

  const handleSend = () => {
    if (!inputText.trim()) return;
    // La logica di invio verrà collegata al backend qui
    console.log("Inviato:", inputText);
    setInputText("");
  };

  return (
    <div className={styles.container}>
      <div className={styles.avatarVideoWrapper}>
        <video
          autoPlay
          loop
          muted
          playsInline
          className={styles.avatarVideo}
        >
          <source src="/AvatarMoneoV2.mp4?v=2" type="video/mp4" />
        </video>
      </div>

      <main className={styles.messageArea}>
        {chatHistory.map((msg) => (
          <div
            key={msg.id}
            className={`${styles.message} ${msg.sender === "user" ? styles.messageUser : styles.messageBot}`}
          >
            <div className={`${styles.bubble} ${msg.sender === "user" ? styles.bubbleUser : styles.bubbleBot}`}>
              {msg.text}
            </div>
          </div>
        ))}
      </main>

      <footer className={styles.inputArea}>
        <div className={styles.inputWrapper}>
          <button className={styles.actionBtn} title="Invia foto">
            <ImageIcon size={20} />
          </button>
          <button className={styles.actionBtn} title="Invia audio">
            <Mic size={20} />
          </button>
          <button className={styles.actionBtn} title="Invia video">
            <Video size={20} />
          </button>

          <input
            type="text"
            placeholder="Scrivi un messaggio..."
            className={styles.input}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
          />

          <button className={styles.sendBtn} onClick={handleSend} title="Invia messaggio">
            <Send size={16} />
          </button>
        </div>
      </footer>
    </div>
  );
}
