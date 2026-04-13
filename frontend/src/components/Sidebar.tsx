"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageCircle, BarChart3, MessageSquarePlus, CreditCard, Wallet } from "lucide-react";
import styles from "./Sidebar.module.css";

export default function Sidebar() {
  const pathname = usePathname();

  const navItems = [
    { name: "Home", path: "/", icon: MessageCircle },
    { name: "Analytics", path: "/analytics", icon: BarChart3 },
  ];

  const bottomNavItems = [
    { name: "Feedback", path: "/feedback", icon: MessageSquarePlus },
    { name: "Abbonamenti", path: "/abbonamenti", icon: CreditCard },
  ];

  return (
    <aside className={styles.sidebar}>
      <div className={styles.logo}>
        <Wallet size={24} />
        <span>Traky / Moneo</span>
      </div>
      
      <nav className={styles.nav}>
        {navItems.map((item) => {
          const isActive = pathname === item.path;
          return (
            <Link 
              key={item.path} 
              href={item.path} 
              className={`${styles.navLink} ${isActive ? styles.navLinkActive : ""}`}
            >
              <item.icon className={styles.icon} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className={styles.bottomNav}>
        <nav className={styles.nav}>
          {bottomNavItems.map((item) => {
            const isActive = pathname === item.path;
            return (
              <Link 
                key={item.path} 
                href={item.path} 
                className={`${styles.navLink} ${isActive ? styles.navLinkActive : ""}`}
              >
                <item.icon className={styles.icon} />
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
