import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ListPage from '../ListPage.jsx';

test('renders title and handles async state update', async () => {
  render(
    <MemoryRouter>
      <ListPage />
    </MemoryRouter>
  );
  await waitFor(() => expect(screen.getByRole('heading', { name: /Accident Reports/i })).toBeInTheDocument());
});
