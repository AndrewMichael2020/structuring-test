import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './styles.css'
import ListPage from './pages/ListPage'
import ReportPage from './pages/ReportPage'

function App(){
  return (
    <BrowserRouter>
      <Routes>
        <Route path='/' element={<ListPage/>} />
        <Route path='/reports/:id' element={<ReportPage/>} />
      </Routes>
    </BrowserRouter>
  )
}

createRoot(document.getElementById('root')).render(<App />)
