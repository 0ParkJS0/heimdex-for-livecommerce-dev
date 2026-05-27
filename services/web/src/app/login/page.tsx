"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login/LoginForm";
import { Auth0LoginPrompt } from "@/components/login/Auth0LoginPrompt";
import { LoginLogoWhite } from "@/components/login/LoginLogoWhite";

export default function LoginPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, isAuth0Enabled } = useAuth();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      const returnTo = sessionStorage.getItem("heimdex_return_to") || "/";
      sessionStorage.removeItem("heimdex_return_to");
      router.replace(returnTo);
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading || isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-grayscale-10">
      {/* Left navy panel — visible on 1280px and above. Stretches to fill viewport height (no white gap) and grows to fill remaining width up to 1976px (covers 1280–2560 viewports with the 584px-wide right pane). */}
      <div className="hidden min-[1280px]:flex flex-1 min-w-[696px] max-w-[1976px] flex-col items-center justify-center bg-heimdex-navy-500 shadow-left-pane rounded-r-[40px]">
        <LoginLogoWhite />
      </div>

      {/* Right form panel — fixed 584px on 1280+ (390px form + 97px gutters); fluid below. Vertical padding scales with viewport height down to 96px so the form never gets clipped on short screens. */}
      <div className="flex-1 min-[1280px]:flex-none min-[1280px]:w-[584px] flex items-center justify-center overflow-clip px-8 py-12 min-[1280px]:px-[97px] min-[1280px]:py-[clamp(96px,29.7vh,304.5px)]">
        {isAuth0Enabled ? <Auth0LoginPrompt /> : <LoginForm />}
      </div>
    </div>
  );
}
