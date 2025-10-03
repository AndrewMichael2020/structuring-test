/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Arial']
      },
      typography: ({ theme }) => ({
        DEFAULT: {
          css: {
            h1: { fontWeight: '700' },
            h2: { fontWeight: '700' },
            h3: { fontWeight: '600' },
            a: { color: theme('colors.sky.700'), textDecoration: 'none' },
            'a:hover': { textDecoration: 'underline' }
          }
        }
      })
    }
  },
  plugins: [require('@tailwindcss/typography')]
};
