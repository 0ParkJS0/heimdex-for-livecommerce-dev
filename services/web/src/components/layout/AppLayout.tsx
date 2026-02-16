"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Sidebar } from "./Sidebar";
import { TopHeader } from "./TopHeader";

interface AppLayoutProps {
  children: React.ReactNode;
}

const NO_LAYOUT_ROUTES = ["/login", "/auth/"];

export function AppLayout({ children }: AppLayoutProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  const skipLayout = NO_LAYOUT_ROUTES.some((route) =>
    route.endsWith("/") ? pathname.startsWith(route) : pathname === route
  );

  useEffect(() => {
    if (!skipLayout && !isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [skipLayout, isLoading, isAuthenticated, router]);

  if (skipLayout) {
    return <>{children}</>;
  }

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="ml-[200px] flex flex-1 flex-col">
        <TopHeader />
        <main className="flex-1 px-6 pb-6">{children}</main>
      </div>
    </div>
  );
}
