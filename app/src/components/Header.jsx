import { Link } from 'react-router-dom';
import Container from './Container.jsx';

export default function Header() {
  return (
    <header className="sticky top-0 z-20 backdrop-blur bg-white/70 border-b border-gray-100">
      <Container className="flex items-center justify-between h-14">
        <Link to="/" className="flex items-center gap-2">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-sky-600 text-white font-semibold">A</span>
          <span className="font-semibold tracking-tight text-lg">Accident Reports</span>
        </Link>
        <nav className="text-sm text-gray-600 hidden sm:flex gap-6">
          <a href="https://github.com/AndrewMichael2020/structuring-test" className="hover:text-gray-900">GitHub</a>
          <a href="/" className="hover:text-gray-900">Home</a>
        </nav>
      </Container>
    </header>
  );
}
