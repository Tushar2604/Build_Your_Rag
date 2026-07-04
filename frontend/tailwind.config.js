/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Warm app canvas — a hair off pure white so white cards lift off it.
        canvas: "#FAFAF9",
        // Accent — refined indigo for interactive/brand moments, links, focus.
        brand: {
          50:  "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
        // Ink — near-black for primary actions and headings (premium, calm).
        ink: {
          DEFAULT: "#18181b",
          950: "#09090b",
          900: "#18181b",
          800: "#27272a",
          700: "#3f3f46",
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        // Soft, layered elevation — subtle at rest, a touch more on hover.
        xs:    "0 1px 2px 0 rgba(24,24,27,0.05)",
        card:  "0 1px 2px rgba(24,24,27,0.04), 0 1px 3px rgba(24,24,27,0.06)",
        pop:   "0 4px 12px rgba(24,24,27,0.08), 0 2px 4px rgba(24,24,27,0.04)",
        modal: "0 16px 48px rgba(24,24,27,0.16), 0 4px 12px rgba(24,24,27,0.08)",
      },
      keyframes: {
        shimmer: {
          "0%":   { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition:  "200% 0" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to:   { opacity: "1" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "translateY(6px) scale(0.98)" },
          to:   { opacity: "1", transform: "translateY(0) scale(1)" },
        },
      },
      animation: {
        shimmer:    "shimmer 1.5s ease-in-out infinite",
        "fade-in":  "fade-in 0.18s ease-out",
        "slide-up": "slide-up 0.24s cubic-bezier(0.16,1,0.3,1)",
        "scale-in": "scale-in 0.18s cubic-bezier(0.16,1,0.3,1)",
      },
    },
  },
  plugins: [],
};
