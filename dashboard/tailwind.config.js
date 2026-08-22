/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        stage: {
          foundation: '#b45309',
          framing: '#0369a1',
          roofing: '#4d7c0f',
          finishing: '#7c3aed',
          approval: '#059669',
        },
        // The brand accent: a deeper, more saturated "drafting blue" than
        // Tailwind's stock `sky`, closer to the ink used on architectural and
        // engineering drawings. Overriding the palette here — rather than
        // introducing a new colour name — means every existing `text-sky-*`,
        // `bg-sky-*`, `border-sky-*`, and `ring-sky-*` utility across the app
        // retints automatically; there is no second accent to keep in sync.
        sky: {
          50: '#eff5fc',
          100: '#dcebf8',
          200: '#b7d4ef',
          300: '#87b6e2',
          400: '#5390d1',
          500: '#2f6fb8',
          600: '#1f5799',
          700: '#1a457c',
          800: '#183a67',
          900: '#152f52',
          950: '#0c1b32',
        },
      },
      fontFamily: {
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          '"Liberation Mono"',
          'monospace',
        ],
      },
      backgroundImage: {
        // A faint drafting-paper grid — pure CSS, no image request. Used
        // sparingly, at very low opacity, behind the app shell.
        blueprint: `linear-gradient(to right, rgb(31 87 153 / 0.05) 1px, transparent 1px),
          linear-gradient(to bottom, rgb(31 87 153 / 0.05) 1px, transparent 1px)`,
      },
      backgroundSize: {
        blueprint: '28px 28px',
      },
    },
  },
  plugins: [],
};
