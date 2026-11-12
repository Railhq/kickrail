import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import { PathrailTag } from "@/components/Pathrail";
import "./globals.css";
import HelprailWidget from "@/components/HelprailWidget";

const PATHRAIL_SITE = process.env.NEXT_PUBLIC_PATHRAIL_SITE || "pr_W8KFAzDx3WV0Htta";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const display = Instrument_Serif({ variable: "--font-instrument", subsets: ["latin"], weight: "400" });

export const metadata: Metadata = {
  title: { default: "Kickrail: affiliate tracking for Stripe", template: "%s · Kickrail" },
  description: "Launch an affiliate program for your Stripe SaaS. Server-side attribution, creator codes, and automatic Stripe payouts.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <PathrailTag site={PATHRAIL_SITE} host="kickrail.com" skip="^/(a|join|view-as)(/|$)" />
      </head>
      <body className={`${sans.variable} ${mono.variable} ${display.variable} font-sans antialiased`}>{children}
        <HelprailWidget skip={["^/a/", "^/a$", "^/join(/|$)", "^/view-as/"]} hosts={["kickrail.com", "www.kickrail.com", "localhost"]} />
      </body>
    </html>
  );
}
