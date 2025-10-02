import React, {useEffect, useState} from 'react'
import axios from 'axios'
import {useParams, Link} from 'react-router-dom'
import ReactMarkdown from 'react-markdown'

export default function ReportPage(){
  const {id} = useParams()
  const [report, setReport] = useState(null)

  useEffect(()=>{
    axios.get(`/api/reports/${id}`).then(r=>{
      setReport(r.data)
      document.title = r.data.title || 'Report'
    }).catch(()=>setReport(null))
  },[id])

  if(report === null) return <div className="p-6">Loading...</div>

  return (
    <div className="prose max-w-3xl mx-auto p-6">
      <h1>{report.title}</h1>
      <div className="text-gray-600">{report.date} · {report.region} · {report.activity}</div>
      <hr />
      <ReactMarkdown>{report.content_markdown}</ReactMarkdown>
      <div className="mt-6"><Link to="/" className="text-blue-600">← Back to list</Link></div>
    </div>
  )
}
