import type { Config } from "tailwindcss";

/**
 * PaceVision design tokens.
 * Colors are stored as space-separated RGB channels in CSS variables
 * (see globals.css) so Tailwind opacity modifiers work via
 * `rgb(var(--x) / <alpha-value>)`. Dark theme is the default (:root);
 * `.light` overrides for the light toggle.
 */
const rgb = (v: string) => `rgb(var(${v}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/app/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        background: rgb("--background"),
        surface: { DEFAULT: rgb("--surface"), 2: rgb("--surface-2") },
        border: rgb("--border"),
        input: rgb("--border"),
        ring: rgb("--primary"),
        foreground: rgb("--foreground"),
        muted: { DEFAULT: rgb("--surface-2"), foreground: rgb("--muted") },
        primary: { DEFAULT: rgb("--primary"), foreground: rgb("--primary-foreground") },
        accent: { DEFAULT: rgb("--accent"), foreground: rgb("--primary-foreground") },
        success: rgb("--success"),
        warning: rgb("--warning"),
        danger: rgb("--danger"),
        // shadcn-style aliases
        card: { DEFAULT: rgb("--surface"), foreground: rgb("--foreground") },
        popover: { DEFAULT: rgb("--surface-2"), foreground: rgb("--foreground") },
        destructive: { DEFAULT: rgb("--danger"), foreground: rgb("--foreground") },
        secondary: { DEFAULT: rgb("--surface-2"), foreground: rgb("--foreground") },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        lg: "0.75rem",
        md: "0.5rem",
        sm: "0.375rem",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.25s ease-out",
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
