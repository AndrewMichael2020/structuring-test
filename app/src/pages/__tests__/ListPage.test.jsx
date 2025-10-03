import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ListPage from '../ListPage.jsx';

test('renders title', () => {
  render(
    <MemoryRouter>
      <ListPage />
    </MemoryRouter>
  );
  expect(screen.getByRole('heading', { name: /Accident Reports/i })).toBeInTheDocument();
});
