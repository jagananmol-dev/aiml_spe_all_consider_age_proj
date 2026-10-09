import type { Metadata } from "next";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "VEDA AI — Industrial Knowledge Intelligence",
  description:
    "AI-powered platform that transforms fragmented industrial knowledge into a unified, queryable, always-updated intelligence layer. Built for refineries, power plants, and manufacturing.",
  keywords: [
    "industrial knowledge management",
    "AI",
    "knowledge graph",
    "maintenance intelligence",
    "compliance automation",
    "RAG",
    "industrial copilot",
  ],
  authors: [{ name: "VEDA AI" }],
  openGraph: {
    title: "VEDA AI — Industrial Knowledge Intelligence",
    description: "The brain that never forgets. The engineer that never sleeps.",
    type: "website",
    locale: "en_IN",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/favicon.ico" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#ffffff" />
      </head>
      <body>{children}</body>
    </html>
  );
}
