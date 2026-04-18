"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis } from "recharts";
import styles from "./analytics.module.css";

const COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042"];

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
    <div className={styles.container}>
      <header className={styles.header}>
        <h1>Analytics</h1>
        <p>Monitora e analizza le tue finanze con Moneo</p>
      </header>

      <div className={styles.grid}>
        {/* FREE CHART */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <h3 className={styles.cardTitle}>Spese per Conto (Mese Corrente)</h3>
          </div>
          <div className={styles.chartContainer}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={accountData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {accountData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip 
                  contentStyle={{ backgroundColor: 'var(--sidebar-border)', borderRadius: '8px', border: 'none', color: 'var(--foreground)' }}
                  itemStyle={{ color: 'var(--foreground)' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* PREMIUM CHART - BAR */}
        <div className={`${styles.card} ${styles.premiumBlur}`}>
          <div className={styles.cardHeader}>
            <h3 className={styles.cardTitle}>Risparmio Mensile nel Tempo</h3>
            <span className={styles.premiumBadge}>Premium</span>
          </div>
          <div className={styles.chartContainer}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={savingsData}>
                <XAxis dataKey="month" stroke="var(--muted-foreground)" />
                <YAxis stroke="var(--muted-foreground)" />
                <Tooltip 
                  contentStyle={{ backgroundColor: 'var(--sidebar-border)', borderRadius: '8px', border: 'none', color: 'var(--foreground)' }}
                />
                <Bar dataKey="amount" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* PREMIUM CHART - PIE */}
        <div className={`${styles.card} ${styles.premiumBlur}`}>
          <div className={styles.cardHeader}>
            <h3 className={styles.cardTitle}>Spese per Categoria</h3>
            <span className={styles.premiumBadge}>Premium</span>
          </div>
          <div className={styles.chartContainer}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={categoryData}
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  dataKey="value"
                >
                  {categoryData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip 
                  contentStyle={{ backgroundColor: 'var(--sidebar-border)', borderRadius: '8px', border: 'none', color: 'var(--foreground)' }}
                  itemStyle={{ color: 'var(--foreground)' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
        
      </div>
    </div>
  );
}
