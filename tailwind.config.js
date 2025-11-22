/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./public/**/*.html",
    "./styles/**/*.css",
    "./src/**/*.py",
    "./public/assets/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ["Fira Code", "monospace"],
      },
      colors: {
        background: "#333333",
        paper: "#f5f4e9",
        accent: "#6c2e2e",
      },
    },
  },
  plugins: [],
};
