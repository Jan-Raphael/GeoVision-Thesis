import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { App } from './App';

describe('App', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              status: 'ok',
              app: 'GeoVision',
              version: '0.1.0',
              environment: 'local',
            }),
        }),
      ),
    );
  });

  it('renders the application name', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'GeoVision' })).toBeInTheDocument();
    // Await the in-flight health request so the component's state update
    // happens inside act() - otherwise React logs an act() warning and the
    // next test inherits a pending promise.
    await screen.findByText('ok');
  });

  it('shows backend status once health resolves', async () => {
    render(<App />);
    expect(await screen.findByText('ok')).toBeInTheDocument();
  });
});
