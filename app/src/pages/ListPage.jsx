import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import SiteLayout from '../layouts/SiteLayout.jsx';
import Container from '../components/Container.jsx';
import Pagination from '../components/Pagination.jsx';
import Loader from '../components/Loader.jsx';
import EmptyState from '../components/EmptyState.jsx';

const PAGE_SIZE = 20;

export default function ListPage() {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const r = await fetch('/api/reports/list');
        if (!r.ok) throw new Error('Failed to load list');
        const data = await r.json();
        // Accept either legacy shape: Array<ReportMeta>
        // or new manifest wrapper: { reports: Array<ReportMeta>, generated_at?, version? }
        let list = [];
        if (Array.isArray(data)) {
          list = data;
        } else if (data && Array.isArray(data.reports)) {
          list = data.reports;
        } else {
          console.warn('Unexpected list payload shape for /api/reports/list', data);
        }
        setReports(list);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return reports;
    return reports.filter((r) => {
      return [r.title, r.peak, r.region, r.activity, r.summary]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [reports, query]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [page, filtered]);

  function fmtDate(d) {
    try {
      return new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return d;
    }
  }

  return (
    <SiteLayout>
      <Container>
        <div className="mb-8">
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Accident Reports</h1>
          <p className="text-gray-600 mt-1">Structured analyses of mountain incidents</p>
        </div>

        <div className="mb-4 flex items-center gap-3">
          <div className="relative flex-1">
            <input
              type="text"
              value={query}
              onChange={(e) => { setPage(1); setQuery(e.target.value); }}
              placeholder="Search by title, region, activity…"
              className="w-full rounded-md border border-gray-300 bg-white/60 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-sky-200"
            />
          </div>
        </div>

        {loading && <Loader />}
        {error && <p className="text-red-600">{error}</p>}
        {!loading && !error && (
          pageItems.length === 0 ? (
            <EmptyState title="No reports yet" subtitle="When reports are published, they will appear here." />
          ) : (
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
              <table className="w-full text-sm">
                <thead className="bg-gray-50/80 text-gray-600 uppercase tracking-wide text-xs">
                  <tr>
                    <th className="text-left p-3">Title</th>
                    <th className="text-left p-3 w-56">Peak / Area</th>
                    <th className="text-left p-3 w-44">Region</th>
                    <th className="text-left p-3 w-44">Activity / Style</th>
                    <th className="text-right p-3 w-24">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {pageItems.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="p-3">
                        <div className="font-medium text-gray-900">{r.title}</div>
                        {r.summary && <div className="text-gray-500 text-xs mt-1 line-clamp-2">{r.summary}</div>}
                      </td>
                      <td className="p-3 whitespace-nowrap">{r.peak}</td>
                      <td className="p-3 whitespace-nowrap">{r.region}</td>
                      <td className="p-3 whitespace-nowrap">{r.activity}</td>
                      <td className="p-3 text-right">
                        <Link className="inline-flex items-center gap-1 text-sky-700 hover:underline" to={`/reports/${r.id}`} state={{ meta: r }}>
                          <span>View</span>
                          <span>→</span>
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-3">
                <Pagination
                  page={page}
                  totalPages={totalPages}
                  onPrev={() => setPage((p) => Math.max(1, p - 1))}
                  onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
                />
              </div>
            </div>
          )
        )}
      </Container>
    </SiteLayout>
  );
}
