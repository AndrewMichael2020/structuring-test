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
          <div className="text-sm text-gray-500"><Link to="/" className="hover:underline">← Back to list</Link></div>
          <h1 className="mt-2 text-2xl sm:text-3xl font-semibold tracking-tight">{apiMeta?.title || meta?.title || `Report ${id}`}</h1>
          <div className="mt-3 flex flex-wrap gap-2">
            {(apiMeta?.date || meta?.date) && <Badge color="slate">{apiMeta?.date || meta?.date}</Badge>}
            {(apiMeta?.region || meta?.region) && <Badge color="sky">{apiMeta?.region || meta?.region}</Badge>}
            {(apiMeta?.activity || meta?.activity) && <Badge color="emerald">{apiMeta?.activity || meta?.activity}</Badge>}
            {!apiMeta && !meta && <Badge color="amber">ID: {id}</Badge>}
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
