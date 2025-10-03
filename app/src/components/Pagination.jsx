export default function Pagination({ page, totalPages, onPrev, onNext }) {
  return (
    <div className="flex items-center justify-between py-3">
      <button
        className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
        onClick={onPrev}
        disabled={page === 1}
      >
        <span>←</span>
        <span>Prev</span>
      </button>
      <div className="text-sm text-gray-600">Page {page} of {totalPages}</div>
      <button
        className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
        onClick={onNext}
        disabled={page === totalPages}
      >
        <span>Next</span>
        <span>→</span>
      </button>
    </div>
  );
}
