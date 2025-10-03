/** @jest-environment node */
import request from 'supertest';
import nock from 'nock';
process.env.GCS_BUCKET = process.env.GCS_BUCKET || 'test-bucket';
import app from './index.js';

const BUCKET = process.env.GCS_BUCKET || 'test-bucket';

describe('server api', () => {
  afterEach(() => nock.cleanAll());

  test('GET /healthz', async () => {
    const res = await request(app).get('/healthz');
    expect(res.status).toBe(200);
    expect(res.text).toBe('ok');
  });

  test('GET /api/reports/list proxies GCS', async () => {
    nock('https://storage.googleapis.com')
      .get(`/${BUCKET}/reports/list.json`)
      .reply(200, [{ id: 'a1' }]);

    const res = await request(app).get('/api/reports/list');
    expect(res.status).toBe(200);
    expect(res.body).toEqual([{ id: 'a1' }]);
  });

  test('GET /api/reports/:id proxies GCS and returns HTML', async () => {
    nock('https://storage.googleapis.com')
      .get(`/${BUCKET}/reports/abc.md`)
      .reply(200, '# Title');

    const res = await request(app).get('/api/reports/abc');
    expect(res.status).toBe(200);
    expect(res.body.id).toBe('abc');
    expect(res.body.content_markdown).toBe('# Title');
    expect(typeof res.body.content_html).toBe('string');
    expect(res.body.content_html).toContain('<h1>');
  });

  test('sanitizes script tags from HTML output', async () => {
    const md = '# Heading\n\n<script>alert(1)</script>\n\nSome text.';
    nock('https://storage.googleapis.com')
      .get(`/${BUCKET}/reports/sanitize.md`)
      .reply(200, md);

    const res = await request(app).get('/api/reports/sanitize');
    expect(res.status).toBe(200);
    expect(res.body.id).toBe('sanitize');
    // raw markdown should include the script string
    expect(res.body.content_markdown).toContain('<script>alert(1)</script>');
    // sanitized HTML must not include any script tags
    expect(res.body.content_html).not.toMatch(/<script/i);
    // but should render other content
    expect(res.body.content_html).toContain('<h1>');
    expect(res.body.content_html).toMatch(/Some text\.?/);
  });
});
