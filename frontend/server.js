const express = require('express')
const fs = require('fs')
const path = require('path')
const cors = require('cors')

const app = express()
app.use(cors())

const FRONTEND_DIR = __dirname
const REPORTS_DIR = path.join(__dirname, '..', 'events', 'reports')

// Serve static frontend assets (index.html, bundle)
app.use(express.static(FRONTEND_DIR))
// Serve generated report markdown files at /reports
if (fs.existsSync(REPORTS_DIR)){
  app.use('/reports', express.static(REPORTS_DIR))
}

function listReports(){
  if(!fs.existsSync(REPORTS_DIR)) return []
  const files = fs.readdirSync(REPORTS_DIR).filter(f=>f.endsWith('.md'))
  const metas = files.map(f=>{
    const content = fs.readFileSync(path.join(REPORTS_DIR,f), 'utf8')
    // naive front-matter parse
    const fm = content.split('---').slice(1,2)[0] || ''
    const meta = {}
    fm.split('\n').forEach(line=>{
      const idx = line.indexOf(':')
      if(idx>0){
        const k = line.slice(0,idx).trim()
        const v = line.slice(idx+1).trim()
        meta[k] = v
      }
    })
    return {
      id: path.basename(f, '.md'),
      date: meta.date || '',
      region: meta.region || '',
      activity: '',
      title: meta.title || path.basename(f, '.md'),
      summary: meta.description || '',
      file_url: `/reports/${path.basename(f)}`
    }
  })
  metas.sort((a,b)=> (b.date || '').localeCompare(a.date || ''))
  return metas
}

app.get('/api/reports/list', (req,res)=>{
  res.json(listReports())
})

app.get('/api/reports/:id', (req,res)=>{
  const id = req.params.id
  const file = path.join(REPORTS_DIR, `${id}.md`)
  if(!fs.existsSync(file)) return res.status(404).json({error:'Not found'})
  const content = fs.readFileSync(file, 'utf8')
  const fm = content.split('---').slice(1,2)[0] || ''
  const meta = {}
  fm.split('\n').forEach(line=>{
    const idx = line.indexOf(':')
    if(idx>0){
      const k = line.slice(0,idx).trim()
      const v = line.slice(idx+1).trim()
      meta[k] = v
    }
  })
  // remove front-matter + json-ld script if present
  let md = content
  // drop first front matter block
  const parts = content.split('---')
  if(parts.length>2) md = parts.slice(2).join('---').trim()
  res.json({
    id,
    title: meta.title || id,
    date: meta.date || '',
    region: meta.region || '',
    activity: meta.activity || '',
    content_markdown: md,
    content_html: ''
  })
})

// Fallback to index.html for SPA routes
app.get('/', (req,res)=>{
  const idx = path.join(FRONTEND_DIR, 'index.html')
  if (fs.existsSync(idx)) return res.sendFile(idx)
  return res.status(404).send('No frontend index available')
})

const port = process.env.PORT || 5173
app.listen(port, ()=> console.log(`Server listening on ${port}`))
