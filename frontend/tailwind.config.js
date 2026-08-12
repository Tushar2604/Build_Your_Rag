/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Palette is variable-driven so the whole app themes at once —
        // see the token block at the top of src/index.css.
        // `white` is deliberately NOT themed: it is the text colour on every
        // coloured button and the overlay tint on dark chrome, and both must
        // stay white in both themes. Panels use `surface`.
        canvas:  "rgb(var(--c-canvas) / <alpha-value>)",
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        // One step above `surface` — nested panels, table headers, inputs
        // sitting on a card.
        "surface-2": "rgb(var(--c-surface-2) / <alpha-value>)",
        gray: {
          50: "rgb(var(--c-gray-50) / <alpha-value>)",
          100: "rgb(var(--c-gray-100) / <alpha-value>)",
          200: "rgb(var(--c-gray-200) / <alpha-value>)",
          300: "rgb(var(--c-gray-300) / <alpha-value>)",
          400: "rgb(var(--c-gray-400) / <alpha-value>)",
          500: "rgb(var(--c-gray-500) / <alpha-value>)",
          600: "rgb(var(--c-gray-600) / <alpha-value>)",
          700: "rgb(var(--c-gray-700) / <alpha-value>)",
          800: "rgb(var(--c-gray-800) / <alpha-value>)",
          900: "rgb(var(--c-gray-900) / <alpha-value>)",
          950: "rgb(var(--c-gray-950) / <alpha-value>)",
        },
        emerald: {
          50: "rgb(var(--c-emerald-50) / <alpha-value>)",
          100: "rgb(var(--c-emerald-100) / <alpha-value>)",
          200: "rgb(var(--c-emerald-200) / <alpha-value>)",
          300: "rgb(var(--c-emerald-300) / <alpha-value>)",
          400: "rgb(var(--c-emerald-400) / <alpha-value>)",
          500: "rgb(var(--c-emerald-500) / <alpha-value>)",
          600: "rgb(var(--c-emerald-600) / <alpha-value>)",
          700: "rgb(var(--c-emerald-700) / <alpha-value>)",
          800: "rgb(var(--c-emerald-800) / <alpha-value>)",
          900: "rgb(var(--c-emerald-900) / <alpha-value>)",
        },
        red: {
          50: "rgb(var(--c-red-50) / <alpha-value>)",
          100: "rgb(var(--c-red-100) / <alpha-value>)",
          200: "rgb(var(--c-red-200) / <alpha-value>)",
          300: "rgb(var(--c-red-300) / <alpha-value>)",
          400: "rgb(var(--c-red-400) / <alpha-value>)",
          500: "rgb(var(--c-red-500) / <alpha-value>)",
          600: "rgb(var(--c-red-600) / <alpha-value>)",
          700: "rgb(var(--c-red-700) / <alpha-value>)",
          800: "rgb(var(--c-red-800) / <alpha-value>)",
          900: "rgb(var(--c-red-900) / <alpha-value>)",
        },
        amber: {
          50: "rgb(var(--c-amber-50) / <alpha-value>)",
          100: "rgb(var(--c-amber-100) / <alpha-value>)",
          200: "rgb(var(--c-amber-200) / <alpha-value>)",
          300: "rgb(var(--c-amber-300) / <alpha-value>)",
          400: "rgb(var(--c-amber-400) / <alpha-value>)",
          500: "rgb(var(--c-amber-500) / <alpha-value>)",
          600: "rgb(var(--c-amber-600) / <alpha-value>)",
          700: "rgb(var(--c-amber-700) / <alpha-value>)",
          800: "rgb(var(--c-amber-800) / <alpha-value>)",
          900: "rgb(var(--c-amber-900) / <alpha-value>)",
        },
        yellow: {
          50: "rgb(var(--c-yellow-50) / <alpha-value>)",
          100: "rgb(var(--c-yellow-100) / <alpha-value>)",
          200: "rgb(var(--c-yellow-200) / <alpha-value>)",
          300: "rgb(var(--c-yellow-300) / <alpha-value>)",
          400: "rgb(var(--c-yellow-400) / <alpha-value>)",
          500: "rgb(var(--c-yellow-500) / <alpha-value>)",
          600: "rgb(var(--c-yellow-600) / <alpha-value>)",
          700: "rgb(var(--c-yellow-700) / <alpha-value>)",
          800: "rgb(var(--c-yellow-800) / <alpha-value>)",
          900: "rgb(var(--c-yellow-900) / <alpha-value>)",
        },
        green: {
          50: "rgb(var(--c-green-50) / <alpha-value>)",
          100: "rgb(var(--c-green-100) / <alpha-value>)",
          200: "rgb(var(--c-green-200) / <alpha-value>)",
          300: "rgb(var(--c-green-300) / <alpha-value>)",
          400: "rgb(var(--c-green-400) / <alpha-value>)",
          500: "rgb(var(--c-green-500) / <alpha-value>)",
          600: "rgb(var(--c-green-600) / <alpha-value>)",
          700: "rgb(var(--c-green-700) / <alpha-value>)",
          800: "rgb(var(--c-green-800) / <alpha-value>)",
          900: "rgb(var(--c-green-900) / <alpha-value>)",
        },
        blue: {
          50: "rgb(var(--c-blue-50) / <alpha-value>)",
          100: "rgb(var(--c-blue-100) / <alpha-value>)",
          200: "rgb(var(--c-blue-200) / <alpha-value>)",
          300: "rgb(var(--c-blue-300) / <alpha-value>)",
          400: "rgb(var(--c-blue-400) / <alpha-value>)",
          500: "rgb(var(--c-blue-500) / <alpha-value>)",
          600: "rgb(var(--c-blue-600) / <alpha-value>)",
          700: "rgb(var(--c-blue-700) / <alpha-value>)",
          800: "rgb(var(--c-blue-800) / <alpha-value>)",
          900: "rgb(var(--c-blue-900) / <alpha-value>)",
        },
        sky: {
          50: "rgb(var(--c-sky-50) / <alpha-value>)",
          100: "rgb(var(--c-sky-100) / <alpha-value>)",
          200: "rgb(var(--c-sky-200) / <alpha-value>)",
          300: "rgb(var(--c-sky-300) / <alpha-value>)",
          400: "rgb(var(--c-sky-400) / <alpha-value>)",
          500: "rgb(var(--c-sky-500) / <alpha-value>)",
          600: "rgb(var(--c-sky-600) / <alpha-value>)",
          700: "rgb(var(--c-sky-700) / <alpha-value>)",
          800: "rgb(var(--c-sky-800) / <alpha-value>)",
          900: "rgb(var(--c-sky-900) / <alpha-value>)",
        },
        indigo: {
          50: "rgb(var(--c-indigo-50) / <alpha-value>)",
          100: "rgb(var(--c-indigo-100) / <alpha-value>)",
          200: "rgb(var(--c-indigo-200) / <alpha-value>)",
          300: "rgb(var(--c-indigo-300) / <alpha-value>)",
          400: "rgb(var(--c-indigo-400) / <alpha-value>)",
          500: "rgb(var(--c-indigo-500) / <alpha-value>)",
          600: "rgb(var(--c-indigo-600) / <alpha-value>)",
          700: "rgb(var(--c-indigo-700) / <alpha-value>)",
          800: "rgb(var(--c-indigo-800) / <alpha-value>)",
          900: "rgb(var(--c-indigo-900) / <alpha-value>)",
        },
        violet: {
          50: "rgb(var(--c-violet-50) / <alpha-value>)",
          100: "rgb(var(--c-violet-100) / <alpha-value>)",
          200: "rgb(var(--c-violet-200) / <alpha-value>)",
          300: "rgb(var(--c-violet-300) / <alpha-value>)",
          400: "rgb(var(--c-violet-400) / <alpha-value>)",
          500: "rgb(var(--c-violet-500) / <alpha-value>)",
          600: "rgb(var(--c-violet-600) / <alpha-value>)",
          700: "rgb(var(--c-violet-700) / <alpha-value>)",
          800: "rgb(var(--c-violet-800) / <alpha-value>)",
          900: "rgb(var(--c-violet-900) / <alpha-value>)",
        },
        purple: {
          50: "rgb(var(--c-purple-50) / <alpha-value>)",
          100: "rgb(var(--c-purple-100) / <alpha-value>)",
          200: "rgb(var(--c-purple-200) / <alpha-value>)",
          300: "rgb(var(--c-purple-300) / <alpha-value>)",
          400: "rgb(var(--c-purple-400) / <alpha-value>)",
          500: "rgb(var(--c-purple-500) / <alpha-value>)",
          600: "rgb(var(--c-purple-600) / <alpha-value>)",
          700: "rgb(var(--c-purple-700) / <alpha-value>)",
          800: "rgb(var(--c-purple-800) / <alpha-value>)",
          900: "rgb(var(--c-purple-900) / <alpha-value>)",
        },
        orange: {
          50: "rgb(var(--c-orange-50) / <alpha-value>)",
          100: "rgb(var(--c-orange-100) / <alpha-value>)",
          200: "rgb(var(--c-orange-200) / <alpha-value>)",
          300: "rgb(var(--c-orange-300) / <alpha-value>)",
          400: "rgb(var(--c-orange-400) / <alpha-value>)",
          500: "rgb(var(--c-orange-500) / <alpha-value>)",
          600: "rgb(var(--c-orange-600) / <alpha-value>)",
          700: "rgb(var(--c-orange-700) / <alpha-value>)",
          800: "rgb(var(--c-orange-800) / <alpha-value>)",
          900: "rgb(var(--c-orange-900) / <alpha-value>)",
        },
        brand: {
          50: "rgb(var(--c-brand-50) / <alpha-value>)",
          100: "rgb(var(--c-brand-100) / <alpha-value>)",
          200: "rgb(var(--c-brand-200) / <alpha-value>)",
          300: "rgb(var(--c-brand-300) / <alpha-value>)",
          400: "rgb(var(--c-brand-400) / <alpha-value>)",
          500: "rgb(var(--c-brand-500) / <alpha-value>)",
          600: "rgb(var(--c-brand-600) / <alpha-value>)",
          700: "rgb(var(--c-brand-700) / <alpha-value>)",
          800: "rgb(var(--c-brand-800) / <alpha-value>)",
          900: "rgb(var(--c-brand-900) / <alpha-value>)",
        },
        // CTA — the warm coral end of the aurora, reserved for primary
        // conversion actions only ("New assistant", "Create workspace").
        // It is the single warm note in a violet system, which is exactly why
        // it reads as "the button to press".
        cta: {
          50:  "#fff5ed",
          100: "#ffe6d5",
          200: "#fecdaa",
          400: "#fb8a3c",
          500: "#f9682f",
          600: "#ea4c1c",
          700: "#c23a12",
        },
        // Ink — the chrome scale (sidebar, top bar, modals). Fixed rather than
        // themed: the console's chrome stays dark in both themes. Tinted violet
        // rather than neutral so it sits inside the aurora instead of on top
        // of it.
        ink: {
          DEFAULT: "#06040d",
          950: "#06040d",
          900: "#0b0817",
          800: "#120e22",
          700: "#1c1733",
        },
      },
      fontFamily: {
        // Body/UI: Plus Jakarta Sans holds up at 12–13px in dense tables.
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'sans-serif'],
        // Display: Sora — geometric, slightly technical, used for headlines,
        // metric numerals and the logotype via `.font-display`.
        display: ['"Sora"', '"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        xl:  "0.875rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      boxShadow: {
        // Elevation on a near-black canvas cannot rely on drop shadow alone —
        // a dark shadow on a dark ground is invisible. Each level therefore
        // pairs a shadow with a 1px inset top highlight, which is what actually
        // separates a glass panel from the page behind it.
        xs:    "0 1px 2px 0 rgba(0,0,0,0.4)",
        card:  "0 1px 2px rgba(0,0,0,0.35), 0 2px 8px -2px rgba(0,0,0,0.45), inset 0 1px 0 0 rgba(255,255,255,0.05)",
        pop:   "0 8px 24px -6px rgba(0,0,0,0.55), inset 0 1px 0 0 rgba(255,255,255,0.06)",
        modal: "0 24px 64px -12px rgba(0,0,0,0.75), 0 8px 24px -8px rgba(124,58,237,0.22), inset 0 1px 0 0 rgba(255,255,255,0.07)",
        // Colored ambient lift — violet bloom on card/row hover.
        lift:  "0 16px 36px -12px rgba(139,92,246,0.42), 0 4px 12px rgba(0,0,0,0.4), inset 0 1px 0 0 rgba(255,255,255,0.08)",
        // Halo rings — the glowing outline around the hero CTA in the design.
        "glow-cta":   "0 0 0 1px rgba(249,104,47,0.35), 0 8px 28px -6px rgba(249,104,47,0.5)",
        "glow-brand": "0 0 0 1px rgba(139,92,246,0.35), 0 8px 28px -6px rgba(139,92,246,0.5)",
        "glow-sm":    "0 0 16px -4px rgba(139,92,246,0.45)",
      },
      backgroundImage: {
        // ── The aurora ───────────────────────────────────────────────────
        // The signature: coral → magenta → violet bleeding in from the edges
        // of a near-black page. Four stops rather than a two-stop linear
        // gradient, because the reference reads as light *sources* behind the
        // panel, not as a painted surface.
        aurora:
          "radial-gradient(ellipse 80% 60% at 8% 4%, rgba(249,115,60,0.55) 0, transparent 60%), " +
          "radial-gradient(ellipse 70% 55% at 92% 10%, rgba(167,80,235,0.55) 0, transparent 62%), " +
          "radial-gradient(ellipse 90% 60% at 78% 92%, rgba(214,64,152,0.42) 0, transparent 60%), " +
          "radial-gradient(ellipse 70% 50% at 20% 96%, rgba(124,58,237,0.38) 0, transparent 62%)",
        // Quieter interior wash for panels sitting inside the shell.
        "aurora-soft":
          "radial-gradient(ellipse 60% 50% at 0% 0%, rgba(249,115,60,0.16) 0, transparent 62%), " +
          "radial-gradient(ellipse 60% 50% at 100% 0%, rgba(167,80,235,0.18) 0, transparent 62%), " +
          "radial-gradient(ellipse 80% 60% at 50% 100%, rgba(124,58,237,0.14) 0, transparent 65%)",
        // Legacy aliases — `mesh-bg` / `mesh-bg-navy` are used on six pages and
        // keep working, now rendering the new aurora instead of the old teal.
        "mesh-light": "radial-gradient(at 12% 16%, rgba(249,115,60,0.20) 0, transparent 52%), radial-gradient(at 88% 12%, rgba(167,80,235,0.24) 0, transparent 52%), radial-gradient(at 50% 92%, rgba(214,64,152,0.18) 0, transparent 56%)",
        "mesh-navy":  "radial-gradient(at 16% 12%, rgba(249,115,60,0.28) 0, transparent 50%), radial-gradient(at 86% 84%, rgba(167,80,235,0.34) 0, transparent 54%)",
        // Dot-matrix texture — the perforated corners in the reference.
        "dot-grid":   "radial-gradient(rgba(255,255,255,0.16) 1px, transparent 1px)",
        // Hairline top edge that fakes a lit bevel on glass.
        "glass-edge": "linear-gradient(180deg, rgba(255,255,255,0.09) 0, rgba(255,255,255,0) 45%)",
      },
      backgroundSize: {
        "dot-sm": "16px 16px",
        "dot-md": "22px 22px",
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
        // The aurora breathes: the light sources swell and drift a little so
        // the page never looks like a static screenshot.
        "aurora-drift": {
          "0%, 100%": { transform: "translate3d(0,0,0) scale(1)",        opacity: "1" },
          "33%":      { transform: "translate3d(-2%,1.5%,0) scale(1.06)", opacity: "0.88" },
          "66%":      { transform: "translate3d(2%,-1%,0) scale(1.03)",   opacity: "0.95" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":      { transform: "translateY(-8px)" },
        },
        "glow-pulse": {
          "0%, 100%": { opacity: "0.55" },
          "50%":      { opacity: "1" },
        },
      },
      animation: {
        shimmer:     "shimmer 1.5s ease-in-out infinite",
        "fade-in":   "fade-in 0.18s ease-out",
        "slide-up":  "slide-up 0.24s cubic-bezier(0.16,1,0.3,1)",
        "scale-in":  "scale-in 0.18s cubic-bezier(0.16,1,0.3,1)",
        "mesh-drift": "mesh-drift 24s ease-in-out infinite",
        "aurora-drift": "aurora-drift 26s ease-in-out infinite",
        float:        "float 7s ease-in-out infinite",
        "glow-pulse": "glow-pulse 4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
