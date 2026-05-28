import type { Metadata } from "next";
import type { ReactNode } from "react";
import { WebVitalsReporter } from "@/components/monitoring/WebVitalsReporter";
import { QueryProvider } from "@/providers/query-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Crypto Radar",
  description: "Realtime signal radar for crypto markets"
};

export default function RootLayout({
  children
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>{children}</QueryProvider>
        <WebVitalsReporter />
      </body>
    </html>
  );
}
