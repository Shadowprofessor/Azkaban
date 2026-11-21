import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AgentProvider } from "@/components/AgentProvider";
import { Shell } from "@/components/Shell";

// next/font self-hosts at build time: the browser never contacts Google.
const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Azkaban",
  description: "Local-first privacy forensics for your own device.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <AgentProvider>
          <Shell>{children}</Shell>
        </AgentProvider>
      </body>
    </html>
  );
}
