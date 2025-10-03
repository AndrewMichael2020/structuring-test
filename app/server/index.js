import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import axios from 'axios';
import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';
import matter from 'gray-matter';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 8080;
const BUCKET = process.env.GCS_BUCKET;

// --- Static serving and SPA catch-all ---
// Serve static files from the 'dist' directory
const distDir = path.resolve(__dirname, '..', 'dist');
app.use(express.static(distDir));

// Health check endpoint - must be at the root
app.get('/healthz', (_req, res) => {
  // For a more robust health check, you could verify GCS connectivity here.
  // For now, a simple 'ok' is sufficient.
  res.status(200).send('ok');
});

// Defer API routes until after static serving is configured, but before the
// catch-all. This is a common pattern for SPAs to avoid conflicts where a
// static file might exist with the same name as an API route.
const apiRouter = express.Router();

apiRouter.get('/reports/list', async (_req, res) => {
  try {
    const url = `https://storage.googleapis.com/${BUCKET}/reports/list.json`;
    const r = await axios.get(url);
    res.json(r.data);
  } catch (e) {
    const errorMessage = e.response?.status === 404
      ? `list.json not found in bucket: ${BUCKET}`
      : String(e);
    console.error(`[API /reports/list] Error: ${errorMessage}`);
    res.status(e.response?.status || 500).json({ error: 'server_error', message: errorMessage });
  }
});

apiRouter.get('/reports/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const mdUrl = `https://storage.googleapis.com/${BUCKET}/reports/${id}.md`;
    const r = await axios.get(mdUrl);

    // Parse front matter and markdown content
    const { content: md, data: meta } = matter(r.data);

    // Sanitize HTML output
    const content_html = sanitizeHtml(marked.parse(md), {
      allowedTags: sanitizeHtml.defaults.allowedTags.concat(['h1', 'h2', 'h3', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td']),
      allowedAttributes: { a: ['href', 'name', 'target', 'rel'], img: ['src', 'alt', 'title'] },
      allowedSchemes: ['http', 'https', 'mailto']
    });

    res.json({ id, content_markdown: md, content_html, meta });
  } catch (e) {
    const errorMessage = e.response?.status === 404
      ? `Report with id '${req.params.id}' not found in bucket: ${BUCKET}`
      : String(e);
    console.error(`[API /reports/:id] Error: ${errorMessage}`);
    res.status(e.response?.status || 500).json({ error: 'server_error', message: errorMessage });
  }
});

app.use('/api', apiRouter);

// This catch-all route should be last. It serves the main index.html for any
// request that didn't match an API route, enabling client-side routing.
app.get('*', (req, res) => {
  res.sendFile(path.join(distDir, 'index.html'));
});

if (process.env.NODE_ENV !== 'test') {
  app.listen(PORT, () => {
    console.log(`Server listening on :${PORT}`);
    if (!BUCKET) {
      console.warn('Warning: GCS_BUCKET is not set. API routes will fail.');
    }
  });
}

export default app;
