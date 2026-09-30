import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { PrivacyProvider } from "@/lib/privacy";

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
    <html lang="en">
      <body className="antialiased">
        <AuthProvider>
          <PrivacyProvider>{children}</PrivacyProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
