/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Warm app canvas — a hair off pure white so white cards lift off it.
        canvas: "#FAFAFA",
        // Accent — teal/turquoise for interactive/brand moments, links, focus, chart fills.
        brand: {
          50:  "#f0fdfa",
          100: "#ccfbf1",
          200: "#99f6e4",
          300: "#5eead4",
          400: "#2dd4bf",
          500: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
          800: "#115e59",
          900: "#134e4a",
        },
        // CTA — warm orange, reserved for primary conversion actions only
        // ("New assistant", "Create workspace", "Upgrade").
        cta: {
          50:  "#fff7ed",
          100: "#ffedd5",
          200: "#fed7aa",
          400: "#fb923c",
          500: "#f97316",
          600: "#ea580c",
          700: "#c2410c",
        },
        // Ink — near-black navy for the sidebar and headings (premium, calm, not flat black).
        ink: {
          DEFAULT: "#0a0a0f",
          950: "#0a0a0f",
          900: "#13131a",
          800: "#1c1c26",
          700: "#2a2a38",
        },
      },
      fontFamily: {
        sans: ['"Inter"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        xl:  "0.875rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      boxShadow: {
        // Soft, layered elevation — subtle at rest, a touch more on hover.
        xs:    "0 1px 2px 0 rgba(10,10,15,0.05)",
        card:  "0 1px 2px rgba(10,10,15,0.04), 0 1px 3px rgba(10,10,15,0.06)",
        pop:   "0 4px 12px rgba(10,10,15,0.08), 0 2px 4px rgba(10,10,15,0.04)",
        modal: "0 16px 48px rgba(10,10,15,0.16), 0 4px 12px rgba(10,10,15,0.08)",
        // Colored ambient lift — used on card/row hover for the "alive" feel.
        lift:  "0 12px 24px -8px rgba(13,148,136,0.18), 0 4px 8px rgba(10,10,15,0.06)",
        "glow-cta": "0 8px 20px -6px rgba(234,88,12,0.35)",
      },
      backgroundImage: {
        "mesh-light": "radial-gradient(at 15% 20%, rgba(94,234,212,0.25) 0, transparent 50%), radial-gradient(at 85% 15%, rgba(196,181,253,0.22) 0, transparent 50%), radial-gradient(at 50% 85%, rgba(253,186,186,0.18) 0, transparent 55%)",
        "mesh-navy":  "radial-gradient(at 20% 15%, rgba(20,184,166,0.16) 0, transparent 45%), radial-gradient(at 80% 80%, rgba(124,58,237,0.10) 0, transparent 50%)",
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
        "mesh-drift": {
          "0%, 100%": { backgroundPosition: "0% 0%, 100% 0%, 50% 100%" },
          "50%":      { backgroundPosition: "20% 10%, 80% 20%, 40% 90%" },
        },
      },
      animation: {
        shimmer:     "shimmer 1.5s ease-in-out infinite",
        "fade-in":   "fade-in 0.18s ease-out",
        "slide-up":  "slide-up 0.24s cubic-bezier(0.16,1,0.3,1)",
        "scale-in":  "scale-in 0.18s cubic-bezier(0.16,1,0.3,1)",
        "mesh-drift": "mesh-drift 24s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
