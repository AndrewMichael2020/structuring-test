import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import SiteLayout from '../layouts/SiteLayout.jsx';
import Container from '../components/Container.jsx';
import Badge from '../components/Badge.jsx';
import Loader from '../components/Loader.jsx';

export default function ReportPage() {
  const { id } = useParams();
  const location = useLocation();
  const meta = location.state?.meta;
  const [content, setContent] = useState('');
  const [html, setHtml] = useState('');
  const [apiMeta, setApiMeta] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const r = await fetch(`/api/reports/${id}`);
        if (!r.ok) throw new Error('Failed to load report');
  const data = await r.json();
  setContent(data.content_markdown || '');
  setHtml(data.content_html || '');
  setApiMeta(data.meta || null);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  return (
    <SiteLayout>
      <div className="bg-gradient-to-r from-sky-50 to-emerald-50 border-y border-gray-100">
        <Container className="py-8">
          <div className="text-sm text-gray-500 flex items-center gap-4">
            <Link to="/" className="hover:underline">← Back to list</Link>
            <Link to="/about" className="hover:underline">About</Link>
          </div>
          <h1 className="mt-2 text-2xl sm:text-3xl font-semibold tracking-tight">{apiMeta?.title || meta?.title || `Report ${id}`}</h1>
          <p className="mt-2 text-sm text-gray-500">Event ID: <span className="font-mono">{id}</span></p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(apiMeta?.date_of_event || meta?.date_of_event || apiMeta?.date || meta?.date) && (
              <Badge color="slate">{apiMeta?.date_of_event || meta?.date_of_event || apiMeta?.date || meta?.date}</Badge>
            )}
            {(apiMeta?.peak || meta?.peak) && <Badge color="sky">{apiMeta?.peak || meta?.peak}</Badge>}
            {(apiMeta?.activity || meta?.activity) && <Badge color="emerald">{apiMeta?.activity || meta?.activity}</Badge>}
          </div>
        </Container>
      </div>
      <Container>
        <div className="prose prose-slate mt-8">
          {loading && <Loader />}
          {error && <p className="text-red-600">{error}</p>}
          {!loading && !error && (
            html ? (
              <div dangerouslySetInnerHTML={{ __html: html }} />
            ) : (
              <ReactMarkdown>{content}</ReactMarkdown>
            )
          )}
        </div>
      </Container>
    </SiteLayout>
  );
}
