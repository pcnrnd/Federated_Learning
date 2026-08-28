/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#070913",
        surface: "rgba(15, 23, 42, 0.55)",
        "surface-2": "rgba(30, 41, 59, 0.7)",
        "surface-3": "rgba(51, 65, 85, 0.45)",
        accent: "#38bdf8",
        ok: "#34d399",
        warn: "#fb923c",
        danger: "#f87171",
        muted: "#94a3b8",
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        'card': '20px',
      },
      boxShadow: {
        'glow-cyan': '0 0 16px rgba(56, 189, 248, 0.2)',
        'glow-green': '0 0 16px rgba(52, 211, 153, 0.2)',
        'glow-red': '0 0 16px rgba(248, 113, 113, 0.2)',
      },
      animation: {
        'pulse-slow': 'pulseGlow 2.5s infinite alternate ease-in-out',
      },
    },
  },
  plugins: [],
}
