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
const DEV_FAKE = (process.env.DEV_FAKE || '0') === '1' || (process.env.DEV_FAKE || '').toLowerCase() === 'true';
const LOCAL_REPORTS_DIR = process.env.LOCAL_REPORTS_DIR || path.resolve(__dirname, '..', '..', 'events', 'reports');
import fs from 'fs/promises';

// Health check endpoint - must be at the root. Place before static middleware
// so that probes reach this route reliably and are not affected by
// static file serving or SPA catch-all behaviour.
// Health check endpoint - respond to any method so probes (GET/HEAD/etc.)
// reliably receive a healthy response. Keep this before static middleware.
app.all('/healthz', (_req, res) => {
  // For a more robust health check, you could verify GCS connectivity here.
  // For now, a simple 'ok' is sufficient. 
  res.status(200).send('ok');
});

// --- Static serving and SPA catch-all ---
// Serve static files from the 'dist' directory
const distDir = path.resolve(__dirname, '..', 'dist');
app.use(express.static(distDir));

// Defer API routes until after static serving is configured, but before the
// catch-all. This is a common pattern for SPAs to avoid conflicts where a
// static file might exist with the same name as an API route.
const apiRouter = express.Router();

apiRouter.get('/reports/list', async (_req, res) => {
  try {
    if (DEV_FAKE) {
      // Return a simple list.json assembled from LOCAL_REPORTS_DIR files
      try {
        const dir = LOCAL_REPORTS_DIR;
        const files = await fs.readdir(dir);
        const ids = files.filter(f => f.endsWith('.md')).map(f => f.replace(/\.md$/, ''));
        const list = ids.map(id => ({ id, url: `/reports/${id}` }));
        return res.json({ reports: list });
      } catch (err) {
        const msg = `DEV_FAKE enabled but LOCAL_REPORTS_DIR read failed: ${err}`;
        console.error(`[API /reports/list] Error: ${msg}`);
        return res.status(500).json({ error: 'server_error', message: msg });
      }
    }
    const url = `https://storage.googleapis.com/${BUCKET}/reports/list.json`;
    try {
      const r = await axios.get(url);
      return res.json(r.data);
    } catch (fetchErr) {
      // If list.json is not present in the bucket, try a public bucket listing
      // fallback. Many deployments write a `reports/list.json` manifest but
      // sometimes the bucket only contains the raw markdown files. If the
      // bucket is publicly listable, we can parse the XML listing and build a
      // minimal list.json on the fly.
      if (fetchErr.response?.status === 404) {
        try {
          const listUrl = `https://storage.googleapis.com/${BUCKET}?prefix=reports/`;
          const listResp = await axios.get(listUrl);
          const xml = listResp.data || '';
          // Extract <Key> elements, filter .md files in the reports/ prefix
          const keys = Array.from(xml.matchAll(/<Key>(.*?)<\/Key>/g)).map(m => m[1]);
          const ids = keys.filter(k => k.startsWith('reports/') && k.endsWith('.md'))
            .map(k => path.basename(k, '.md'));
          const list = ids.map(id => ({ id, url: `/reports/${id}` }));
          console.warn(`[API /reports/list] list.json missing; returning manifest from public bucket listing (${ids.length} items)`);
          return res.json({ reports: list });
        } catch (listErr) {
          const errorMessage = `list.json not found in bucket: ${BUCKET}`;
          console.error(`[API /reports/list] Error: ${errorMessage} (and public listing fallback failed: ${listErr})`);
          return res.status(404).json({ error: 'server_error', message: errorMessage });
        }
      }
      const errorMessage = fetchErr.response?.status === 404
        ? `list.json not found in bucket: ${BUCKET}`
        : String(fetchErr);
      console.error(`[API /reports/list] Error: ${errorMessage}`);
      return res.status(fetchErr.response?.status || 500).json({ error: 'server_error', message: errorMessage });
    }
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
    if (DEV_FAKE) {
      // Read local markdown from LOCAL_REPORTS_DIR
      try {
        const mdPath = path.join(LOCAL_REPORTS_DIR, `${id}.md`);
        const data = await fs.readFile(mdPath, 'utf-8');
        const { content: md, data: meta } = matter(data);
        const content_html = sanitizeHtml(marked.parse(md), {
          allowedTags: sanitizeHtml.defaults.allowedTags.concat(['h1', 'h2', 'h3', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td']),
          allowedAttributes: { a: ['href', 'name', 'target', 'rel'], img: ['src', 'alt', 'title'] },
          allowedSchemes: ['http', 'https', 'mailto']
        });
        return res.json({ id, content_markdown: md, content_html, meta });
      } catch (err) {
        const msg = `DEV_FAKE enabled but failed to read ${id}.md from ${LOCAL_REPORTS_DIR}: ${err}`;
        console.error(`[API /reports/:id] Error: ${msg}`);
        return res.status(404).json({ error: 'not_found', message: msg });
      }
    }
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
