import React from "react";
import { Sidebar } from "../Sidebar/Sidebar";
import { Header } from "./Header";

interface MainLayoutProps {
  children: React.ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="ducta-app-layout">
      <Sidebar />
      <div className="ducta-main-container">
        <Header />
        <main className="ducta-content">
          {children}
        </main>
      </div>
    </div>
  );
}
