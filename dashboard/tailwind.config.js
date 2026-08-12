/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Placeholder brand ramp; the real palette lands with Module 11.
        stage: {
          foundation: '#b45309',
          framing: '#0369a1',
          roofing: '#4d7c0f',
          finishing: '#7c3aed',
          approval: '#059669',
        },
      },
    },
  },
  plugins: [],
};
