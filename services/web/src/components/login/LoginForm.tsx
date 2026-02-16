"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function LoginForm() {
  const router = useRouter();
  const { loginWithCredentials, isLoading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isFormValid = email.trim() !== "" && password.trim() !== "";
  const isDisabled = !isFormValid || submitting || isLoading;
  const hasError = error !== null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (isDisabled) return;

    setError(null);
    setSubmitting(true);

    try {
      await loginWithCredentials(email, password);
      router.replace("/");
    } catch {
      setError("이메일 또는 비밀번호가 올바르지 않습니다. 다시 확인해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

  const clearError = () => {
    if (error) setError(null);
  };

  return (
    <form onSubmit={handleSubmit} noValidate>
      <p className="text-gray-500 text-[15px] mb-10">전달받은 이메일/비밀번호로 로그인해 주세요.</p>

      <div className="mb-5">
        <label htmlFor="login-email" className="block text-sm font-bold text-gray-900 mb-2">
          이메일
        </label>
        <input
          id="login-email"
          type="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            clearError();
          }}
          placeholder="이메일 입력"
          className={cn(
            "w-full px-4 py-3 border rounded-lg text-sm outline-none transition-colors",
            hasError
              ? "border-red-500 focus:border-red-500"
              : "border-gray-300 focus:border-indigo-400"
          )}
          autoComplete="email"
          disabled={submitting}
        />
      </div>

      <div className="mb-2">
        <label htmlFor="login-password" className="block text-sm font-bold text-gray-900 mb-2">
          비밀번호
        </label>
        <div className="relative">
          <input
            id="login-password"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              clearError();
            }}
            placeholder="비밀번호 입력"
            className={cn(
              "w-full px-4 py-3 pr-12 border rounded-lg text-sm outline-none transition-colors",
              hasError
                ? "border-red-500 focus:border-red-500"
                : "border-gray-300 focus:border-indigo-400"
            )}
            autoComplete="current-password"
            disabled={submitting}
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
            tabIndex={-1}
            aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
          >
            {showPassword ? <EyeIcon /> : <EyeOffIcon />}
          </button>
        </div>
      </div>

      {hasError && <p className="text-red-500 text-sm mt-2">{error}</p>}

      <div className={cn(hasError ? "mt-4" : "mt-8")}>
        <button
          type="submit"
          disabled={isDisabled}
          className={cn(
            "w-full py-3.5 rounded-lg text-sm font-medium transition-colors",
            isDisabled
              ? "bg-[#B8B8BE] text-white cursor-not-allowed"
              : "bg-indigo-500 text-white hover:bg-indigo-600 active:bg-indigo-700"
          )}
        >
          {submitting ? "로그인 중..." : "로그인"}
        </button>
      </div>
    </form>
  );
}

function EyeIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}
