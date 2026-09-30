import type { Metadata } from "next";
import { Unbounded, Hanken_Grotesk, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { PrivacyProvider } from "@/lib/privacy";

const unbounded = Unbounded({
  subsets: ["latin"],
  variable: "--font-unbounded",
});

const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: "Tapestry",
  description: "AI-powered memory capture and enhancement",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${unbounded.variable} ${hanken.variable} ${plexMono.variable}`}>
      <body className="antialiased">
        <AuthProvider>
          <PrivacyProvider>{children}</PrivacyProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
