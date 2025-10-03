const express = require('express');
const path = require('path');
const axios = require('axios');
const { marked } = require('marked');
const sanitizeHtml = require('sanitize-html');
const matter = require('gray-matter');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 8080;
const BUCKET = process.env.GCS_BUCKET;
const DEV_FAKE = process.env.DEV_FAKE === '1';
const LOCAL_REPORTS_DIR = process.env.LOCAL_REPORTS_DIR || path.resolve(__dirname, '..', '..', 'events', 'reports');

if (DEV_FAKE) {
  console.log('DEV_FAKE=1: serving mock API responses');
} else if (!BUCKET) {
  console.warn('Warning: GCS_BUCKET not set. API routes may fail. Set DEV_FAKE=1 to use local mocks.');
}

app.get('/api/reports/list', async (_req, res) => {
  try {
    if (DEV_FAKE) {
      const data = [
        {
          id: '749f8e98f4a5',
          date: '2025-05-10',
          region: 'WA',
          activity: 'Alpine Rock',
          title: 'North Early Winters Spire anchor failure',
          summary: 'Anchor failure during descent, late-day weather.'
        }
      ];
      console.log('DEV_FAKE list ->', data);
      return res.json(data);
    }
    const url = `https://storage.googleapis.com/${BUCKET}/reports/list.json`;
    const r = await axios.get(url);
    res.json(r.data);
  } catch (e) {
    res.status(500).json({ error: 'server_error', message: String(e) });
  }
});

app.get('/api/reports/:id', async (req, res) => {
  try {
    const rawId = req.params.id;
    const id = rawId.endsWith('.md') ? rawId.slice(0, -3) : rawId;
    if (DEV_FAKE) {
      const md = `# Sample Report\n\nThis is a mock report for ${id}.`;
      const html = sanitizeHtml(marked.parse(md), {
        allowedTags: sanitizeHtml.defaults.allowedTags.concat(['h1', 'h2', 'h3', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td']),
        allowedAttributes: { a: ['href', 'name', 'target', 'rel'], img: ['src', 'alt', 'title'] },
        allowedSchemes: ['http', 'https', 'mailto']
      });
      const payload = { id, content_markdown: md, content_html: html };
      console.log('DEV_FAKE report ->', id);
      return res.json(payload);
    }
    // Local file fallback if exists
    try {
      const filePath = path.join(LOCAL_REPORTS_DIR, `${id}.md`);
      if (fs.existsSync(filePath)) {
        const raw = fs.readFileSync(filePath, 'utf-8');
        const { content: md, data } = matter(raw);
        const html = sanitizeHtml(marked.parse(md), {
          allowedTags: sanitizeHtml.defaults.allowedTags.concat(['h1', 'h2', 'h3', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td']),
          allowedAttributes: { a: ['href', 'name', 'target', 'rel'], img: ['src', 'alt', 'title'] },
          allowedSchemes: ['http', 'https', 'mailto']
        });
        const meta = {
          id,
          title: data.title || undefined,
          date: data.date || undefined,
          region: data.region || undefined,
          activity: data.activity || data.activity_style || undefined,
          description: data.description || undefined
        };
        return res.json({ id, content_markdown: md, content_html: html, meta });
      }
    } catch (err) {
      // ignore and try GCS
    }
    const url = `https://storage.googleapis.com/${BUCKET}/reports/${id}.md`;
    const r = await axios.get(url);
    const { content: md, data } = matter(r.data);
    const html = sanitizeHtml(marked.parse(md), {
      allowedTags: sanitizeHtml.defaults.allowedTags.concat(['h1', 'h2', 'h3', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td']),
      allowedAttributes: { a: ['href', 'name', 'target', 'rel'], img: ['src', 'alt', 'title'] },
      allowedSchemes: ['http', 'https', 'mailto']
    });
    const meta = {
      id,
      title: data.title || undefined,
      date: data.date || undefined,
      region: data.region || undefined,
      activity: data.activity || data.activity_style || undefined,
      description: data.description || undefined
    };
    res.json({ id, content_markdown: md, content_html: html, meta });
  } catch (e) {
    res.status(500).json({ error: 'server_error', message: String(e) });
  }
});

app.get('/healthz', (_req, res) => res.send('ok'));

const distDir = path.resolve(__dirname, '..', 'dist');
app.use(express.static(distDir));
app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/') || req.path === '/healthz') return next();
  res.sendFile(path.join(distDir, 'index.html'));
});

if (process.env.NODE_ENV !== 'test') {
  app.listen(PORT, () => console.log(`listening on :${PORT}`));
}

module.exports = app;
