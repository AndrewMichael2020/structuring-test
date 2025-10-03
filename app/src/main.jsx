import React from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import './styles.css';
import ListPage from './pages/ListPage.jsx';
import ReportPage from './pages/ReportPage.jsx';

const router = createBrowserRouter([
  { path: '/', element: <ListPage /> },
  { path: '/reports/:id', element: <ReportPage /> }
]);

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
