Accident Reports Frontend

Quickstart (development):

# install
cd frontend
npm install

# run the tiny express API + Vite dev server (the server.js serves API endpoints)
npm run dev

# or run the Node server which reads generated Markdown from ../events/reports
node server.js

Notes:
- The server expects generated report markdown files under ../events/reports/*.md
- The simple Express server exposes:
  - GET /api/reports/list
  - GET /api/reports/:id
- For static hosting consider building a Next.js app with getStaticProps that reads the same MD files.
