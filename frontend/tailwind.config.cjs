module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
  theme: {
    extend: {
      colors: {
        cortexBlue: "#2563EB",
        cortexGray: "#F9FAFB"
      }
    }
  },
  plugins: [require("@tailwindcss/typography")]
};