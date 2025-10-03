#!/usr/bin/env node
// CommonJS wrapper to invoke the app's validation script so node modules resolve
const { spawnSync } = require('child_process');
const path = require('path');
const appScript = path.resolve(__dirname, '..', 'app', 'scripts', 'validate-artifacts.js');
const res = spawnSync(process.execPath, [appScript], { stdio: 'inherit' });
process.exit(res.status ?? 1);
import fs from 'fs';
import path from 'path';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import axios from 'axios';

const __dirname = path.dirname(new URL(import.meta.url).pathname);
const root = path.resolve(__dirname, '..');

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);

const listSchema = JSON.parse(fs.readFileSync(path.join(root, 'schemas', 'list.schema.json'), 'utf-8'));
const reportSchema = JSON.parse(fs.readFileSync(path.join(root, 'schemas', 'report.schema.json'), 'utf-8'));
const validateList = ajv.compile(listSchema);
const validateReport = ajv.compile(reportSchema);

async function main() {
  const bucket = process.env.GCS_BUCKET || process.env.BUCKET;
  let list;
  if (bucket) {
    const url = `https://storage.googleapis.com/${bucket}/reports/list.json`;
    const r = await axios.get(url);
    list = r.data;
  } else {
    // fallback sample
    list = [
      {
        id: '749f8e98f4a5',
        date: '2025-05-10',
        region: 'WA',
        activity: 'Alpine Rock',
        title: 'North Early Winters Spire anchor failure',
        summary: 'Anchor failure during descent, late-day weather.'
      }
    ];
  }

  if (!validateList(list)) {
    console.error('list.json failed schema validation');
    console.error(validateList.errors);
    process.exit(1);
  }

  // sample: check first item has corresponding markdown in bucket when provided
  if (bucket && list.length > 0) {
    const headUrl = `https://storage.googleapis.com/${bucket}/reports/${list[0].id}.md`;
    const res = await axios.get(headUrl);
    const report = { id: list[0].id, content_markdown: res.data };
    if (!validateReport(report)) {
      console.error('report JSON failed schema validation');
      console.error(validateReport.errors);
      process.exit(1);
    }
  }

  console.log('Schema validation passed');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
