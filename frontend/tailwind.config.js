/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Segoe UI"', "system-ui", "sans-serif"],
        mono: ['"Cascadia Code"', "Consolas", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
