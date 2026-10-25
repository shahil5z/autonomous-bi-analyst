import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ABI Analyst",
  description: "A question-answering analyst for an online retail dataset: SQL and Python compute the numbers, an LLM only explains them.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
