/** @type {import('tailwindcss').Config} */

/* The tokens live in `src/index.css` as CSS variables; this file only teaches
   Tailwind their names. Keeping the values in CSS means a theme is inspectable
   in the browser and changeable in one file, rather than compiled away into a
   thousand utility classes. */
const ink = (v) => `rgb(var(${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: {
          DEFAULT: ink("--paper"),
          raised: ink("--paper-raised"),
          sunken: ink("--paper-sunken"),
        },
        ink: {
          DEFAULT: ink("--ink"),
          soft: ink("--ink-soft"),
          faint: ink("--ink-faint"),
        },
        rule: {
          DEFAULT: ink("--rule"),
          strong: ink("--rule-strong"),
        },
        volt: { DEFAULT: ink("--volt"), ink: ink("--volt-ink") },
        positive: { DEFAULT: ink("--positive"), bg: ink("--positive-bg") },
        caution: { DEFAULT: ink("--caution"), bg: ink("--caution-bg") },
        critical: { DEFAULT: ink("--critical"), bg: ink("--critical-bg") },
      },
      fontFamily: {
        sans: ['"Space Grotesk"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      /* A deliberately tight type scale. Editorial hierarchy comes from weight,
         tracking and space around type — not from twelve sizes. */
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
        display: ["clamp(2.75rem, 7vw, 5.5rem)", { lineHeight: "0.94", letterSpacing: "-0.035em" }],
        title: ["clamp(1.75rem, 3.2vw, 2.75rem)", { lineHeight: "1.05", letterSpacing: "-0.025em" }],
        heading: ["1.25rem", { lineHeight: "1.25", letterSpacing: "-0.015em" }],
      },
      borderRadius: {
        /* Small radii only. Large pill-shaped cards are the single clearest
           "generic template" signal, and a datasheet does not have them. */
        plate: "3px",
      },
      transitionTimingFunction: {
        out: "var(--ease-out)",
        inout: "var(--ease-inout)",
      },
      transitionDuration: {
        fast: "var(--dur-fast)",
        base: "var(--dur-base)",
      },
      maxWidth: { shell: "88rem" },
    },
  },
  plugins: [],
};
