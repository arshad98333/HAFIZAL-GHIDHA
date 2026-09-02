/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        gcc: {
          navy: "#0C447C",
          teal: "#085041",
          sand: "#F5F0E8",
          gold: "#C4A35A",
          crimson: "#8B1E3F",
        },
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans Arabic", "system-ui", "sans-serif"],
        display: ["Inter", "Noto Sans Arabic", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
