import Container from './Container.jsx';

export default function Footer() {
  return (
    <footer className="border-t border-gray-100 bg-white">
      <Container className="py-6 text-sm text-gray-500 flex items-center justify-between">
  <span>© {new Date().getFullYear()} Andrew M. Ihnativ</span>
        <span className="hidden sm:block">Built with React + Tailwind, deployed to Cloud Run</span>
      </Container>
    </footer>
  );
}
