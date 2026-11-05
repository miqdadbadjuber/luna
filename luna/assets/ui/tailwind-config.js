tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter"', 'sans-serif'],
        montserrat: ['"Inter"', 'sans-serif'],
        display: ['"Inter"', 'sans-serif'],
        mono: ['"Inter"', 'monospace'],
      },
      colors: {
        void: '#000000',
        obsidian: '#09090b',
        'obsidian-light': '#141417',
        'obsidian-card': '#111113',
        emerald: {
          300: '#6ee7b7',
          400: '#34d399',
          500: '#10b981',
          600: '#059669',
          700: '#047857',
          900: '#064e3b',
          950: '#022c22',
        },
        zinc: {
          300: '#d4d4d8',
          400: '#a1a1aa',
          500: '#71717a',
          700: '#3f3f46',
          800: '#27272a',
          900: '#18181b',
          950: '#09090b',
        }
      },
      boxShadow: {
        'glow-emerald': 'none',
        'capsule': '0 20px 50px rgba(0, 0, 0, 0.8)',
      }
    }
  }
}
