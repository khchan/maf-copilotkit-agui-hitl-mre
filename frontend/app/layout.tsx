import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MAF CopilotKit AG-UI HITL MRE",
  description: "Minimal repro for MAF AG-UI workflow HITL with CopilotKit hooks",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
