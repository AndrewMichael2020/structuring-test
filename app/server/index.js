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

if (!BUCKET) {
  console.warn('Warning: GCS_BUCKET not set. API routes will fail.');
}

// --- API Routes ---

// Health check endpoint
app.get('/healthz', (_req, res) => res.send('ok'));

app.get('/api/reports/list', async (_req, res) => {
  try {
    const url = `https://storage.googleapis.com/${BUCKET}/reports/list.json`;
    const r = await axios.get(url);
    res.json(r.data);
  } catch (e) {
    res.status(500).json({ error: 'server_error', message: String(e) });
  }
});

app.get('/api/reports/:id', async (req, res) => {
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
    res.status(500).json({ error: 'server_error', message: String(e) });
  }
});

// Static serving when built
const distDir = path.resolve(__dirname, '..', 'dist');
app.use(express.static(distDir));

// This catch-all route should be last. It serves the main index.html for any
// request that didn't match an API route, enabling client-side routing.
app.get('*', (req, res) => {
  res.sendFile(path.join(distDir, 'index.html'));
});

if (process.env.NODE_ENV !== 'test') {
  app.listen(PORT, () => console.log(`listening on :${PORT}`));
}

export default app;
