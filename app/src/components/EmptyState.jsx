export default function EmptyState({ title = 'No results', subtitle = 'Try adjusting filters or check back later.' }) {
  return (
    <div className="text-center py-16">
      <div className="mx-auto w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center text-gray-500">∅</div>
      <h3 className="mt-4 text-lg font-medium text-gray-900">{title}</h3>
      <p className="mt-1 text-gray-500">{subtitle}</p>
    </div>
  );
}
