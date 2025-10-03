import Header from '../components/Header.jsx';
import Footer from '../components/Footer.jsx';

export default function SiteLayout({ children }) {
  return (
    <div className="min-h-dvh bg-gradient-to-b from-white to-slate-50 text-slate-900">
      <Header />
      <main className="py-8">{children}</main>
      <Footer />
    </div>
  );
}
