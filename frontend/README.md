# Frontend

Rowset uses Django templates, HTMX, Alpine.js, Tailwind, and a small PostCSS
asset build. There is no Webpack bundle.

## Available Scripts

### `npm run build`

Compiles `frontend/src/styles/index.css`, copies `frontend/src/js`, copies
vendor images, and copies Alpine.js into `frontend/build`.

### `npm run start`

Runs the same asset build in watch mode for local Docker development.

### `npm run watch`

Alias for the watch-mode asset build.
