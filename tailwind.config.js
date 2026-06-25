module.exports = {
  darkMode: 'class',
  content: [
    './frontend/templates/**/*.html',
    './frontend/src/**/*.js',
    './core/**/*.py',
    './apps/**/*.py',
    './rowset/**/*.py',
  ],
  theme: {
    extend: {},
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/forms'),
  ],
};
