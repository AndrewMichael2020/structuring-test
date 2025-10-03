import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import axios from 'axios';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 8080;
const BUCKET = process.env.GCS_BUCKET;

if (!BUCKET) {
  console.warn('Warning: GCS_BUCKET not set. API routes will fail.');
}

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
    const url = `https://storage.googleapis.com/${BUCKET}/reports/${id}.md`;
    const r = await axios.get(url);
    res.json({ id, content_markdown: r.data });
  } catch (e) {
    res.status(500).json({ error: 'server_error', message: String(e) });
  }
});

app.get('/healthz', (_req, res) => res.send('ok'));

// Static serving when built
const distDir = path.resolve(__dirname, '..', 'dist');
app.use(express.static(distDir));
app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/')) return next();
  res.sendFile(path.join(distDir, 'index.html'));
});

if (process.env.NODE_ENV !== 'test') {
  app.listen(PORT, () => console.log(`listening on :${PORT}`));
}

export default app;
