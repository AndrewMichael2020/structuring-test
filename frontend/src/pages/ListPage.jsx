import React, {useEffect, useState} from 'react'
import axios from 'axios'
import { Link } from 'react-router-dom'

const PAGE_SIZE = 10

export default function ListPage(){
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)

  useEffect(()=>{
    axios.get('/api/reports/list').then(r=>{
      setItems(r.data || [])
    }).catch(()=>setItems([]))
  },[])

  const total = items.length
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const start = (page-1)*PAGE_SIZE
  const pageItems = items.slice(start, start+PAGE_SIZE)

  return (
    <div className="p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">🏔️ Accident Reports</h1>
        <p className="text-gray-600">Structured analyses of mountain incidents</p>
      </header>

      <table className="table-auto w-full text-sm border-t border-b">
        <thead className="sticky top-0 bg-white">
          <tr>
            <th className="text-left p-2">Date</th>
            <th className="text-left p-2">Region</th>
            <th className="text-left p-2">Activity</th>
            <th className="text-left p-2">Title</th>
            <th className="p-2"> </th>
          </tr>
        </thead>
        <tbody>
          {pageItems.map(it=> (
            <tr key={it.id} className="hover:bg-gray-50">
              <td className="p-2 align-top">{it.date}</td>
              <td className="p-2 align-top">{it.region}</td>
              <td className="p-2 align-top">{it.activity}</td>
              <td className="p-2 align-top">{it.title}</td>
              <td className="p-2 align-top"><Link to={`/reports/${it.id}`} className="text-blue-600">➜ View</Link></td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-4 flex items-center justify-between">
        <button onClick={()=>setPage(Math.max(1,page-1))} className="px-3 py-1 border rounded">◀ Prev</button>
        <div>Page {page} of {pages}</div>
        <button onClick={()=>setPage(Math.min(pages,page+1))} className="px-3 py-1 border rounded">Next ▶</button>
      </div>
    </div>
  )
}
