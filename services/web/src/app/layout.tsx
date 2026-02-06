import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Heimdex - Video Search",
  description: "Search your video library with natural language",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  );
}
