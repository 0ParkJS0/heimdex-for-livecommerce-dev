import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/features/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        pretendard: ["var(--font-pretendard)", "system-ui", "sans-serif"],
        "noto-kr": ["var(--font-noto-kr)", "system-ui", "sans-serif"],
      },
      colors: {
        primary: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
        },
        "heimdex-navy": {
          400: "#496a94",
          500: "#234c77",
          600: "#1c456f",
          700: "#1a3d61",
        },
        grayscale: {
          10: "#fcfcff",
          100: "#e8e9f8",
          200: "#d9dae9",
          300: "#c4c5d4",
          400: "#9e9fae",
          500: "#7c7d8b",
          800: "#272833",
        },
        "neutral-h": {
          50: "#f5f5f5",
          100: "#e9e9e9",
          200: "#d9d9d9",
          300: "#c4c4c4",
          400: "#9d9d9d",
          500: "#7b7b7b",
          600: "#555555",
          700: "#444551",
          800: "#262626",
        },
        "red-h": {
          50: "#f7e9ec",
          400: "#d53b49",
          500: "#d81d2f",
        },
        "green-h": {
          50: "#e5f4eb",
          400: "#3fb675",
          500: "#00a95e",
        },
        "amber-h": {
          50: "#ffefda",
          500: "#e07f00",
        },
        softblue: {
          600: "#3b83f6",
        },
      },
      boxShadow: {
        card: "0px 4px 20px 0px rgba(232, 233, 248, 1)",
        "card-lg":
          "0px 4px 20px 0px rgba(232, 233, 248, 1), 10px 10px 20px 0px rgba(185, 185, 185, 0.1)",
        dialog: "2px 2px 20px 0px rgba(0, 0, 0, 0.25)",
        input: "10px 10px 20px 0px rgba(185, 185, 185, 0.1)",
        "left-pane": "10px 10px 20px 0px #f1f1ff",
      },
      borderRadius: {
        card: "10px",
        dialog: "20px",
      },
    },
  },
  plugins: [],
};

export default config;
