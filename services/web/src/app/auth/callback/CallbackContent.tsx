"use client";

import { useEffect } from "react";
import { useAuth0 } from "@auth0/auth0-react";
import { useRouter } from "next/navigation";
import { isAuth0Enabled } from "@/lib/auth";

export default function CallbackContent() {
  const router = useRouter();

  if (!isAuth0Enabled) {
    return <CallbackFallback router={router} />;
  }

  return <Auth0Callback router={router} />;
}

function Auth0Callback({ router }: { router: ReturnType<typeof useRouter> }) {
  const { isLoading, error, isAuthenticated } = useAuth0();

  useEffect(() => {
    if (isLoading) return;

    if (error) {
      console.error("[Heimdex] Auth0 callback error:", error);
    }

    router.replace("/");
  }, [isLoading, error, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500 mx-auto mb-4" />
          <p className="text-gray-600">Completing login...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md mx-auto p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Login Error</h2>
          <p className="text-gray-600 mb-4">{error.message}</p>
          <button
            onClick={() => router.replace("/")}
            className="px-4 py-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600"
          >
            Return to Home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500 mx-auto mb-4" />
        <p className="text-gray-600">Redirecting...</p>
      </div>
    </div>
  );
}

function CallbackFallback({ router }: { router: ReturnType<typeof useRouter> }) {
  useEffect(() => {
    router.replace("/");
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <p className="text-gray-600">Redirecting...</p>
    </div>
  );
}
