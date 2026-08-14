/**
 * Component tests for the public surface.
 *
 * The assertions that earn their keep are the ones about **what a visitor is
 * told**: that a progress figure is labelled an estimate, that the approval
 * stage explains it needs an inspection, that a private profile leaks nothing
 * but a username, and that a private project reads as "not available" rather
 * than as an error. Those are promises the system makes, not styling.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ProgressRing, StageBars, StatusBadge } from '@/components/progress';
import { CaptureStrip, PrivateAccountNotice, ProjectCard } from '@/components/project';
import type * as ApiModule from '@/lib/api';
import { ApiError, type CaptureSummary, type FeedProject, type StageBreakdown } from '@/lib/api';
import { ProfilePage } from '@/pages/misc';
import { ProjectPage } from '@/pages/project';

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof ApiModule>('@/lib/api');
  return { ...actual, fetchProject: vi.fn(), fetchProfile: vi.fn(), fetchFeed: vi.fn() };
});

const api = await import('@/lib/api');

function renderWithProviders(ui: React.ReactNode, route = '/') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const STAGES: StageBreakdown = {
  foundation_pct: 100,
  framing_pct: 60,
  roofing_pct: 0,
  finishing_pct: 0,
  approval_pct: 0,
};

const PROJECT: FeedProject = {
  id: 'p1',
  project_code: 'NG_00',
  name: 'Jollibee Naga Branch',
  intended_use: 'Fast-food restaurant',
  location_label: 'Panganiban Dr, Naga City',
  latitude: 13.6218,
  longitude: 123.1948,
  progress_pct: 38.5,
  macro_stage: 'framing',
  status: 'active',
  deadline_date: '2026-12-31',
  last_capture_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  map_url: 'https://maps.example/NG_00',
};

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ProgressRing', () => {
  it('labels the figure as an AI estimate', () => {
    render(<ProgressRing value={38.5} />);
    expect(screen.getByText('38.5%')).toBeInTheDocument();
    expect(screen.getByText('AI estimate')).toBeInTheDocument();
  });

  it('calls a finished project verified rather than estimated', () => {
    render(<ProgressRing value={100} />);
    expect(screen.getByText('Verified')).toBeInTheDocument();
  });

  it('exposes the value to assistive technology, not only as an arc', () => {
    render(<ProgressRing value={38.5} />);
    expect(screen.getByRole('img', { name: /38.5 percent complete/i })).toBeInTheDocument();
  });

  it('clamps a value outside 0-100 rather than drawing past the ring', () => {
    render(<ProgressRing value={140} />);
    expect(screen.getByText('100.0%')).toBeInTheDocument();
  });
});

describe('StageBars', () => {
  it('renders all five stages with accessible progress semantics', () => {
    render(<StageBars stages={STAGES} />);
    expect(screen.getAllByRole('progressbar')).toHaveLength(5);
    expect(screen.getByRole('progressbar', { name: 'Framing' })).toHaveAttribute(
      'aria-valuenow',
      '60',
    );
  });

  it('explains that the approval stage needs a physical inspection', () => {
    render(<StageBars stages={STAGES} />);
    expect(screen.getByText(/requires inspection/i)).toBeInTheDocument();
  });
});

describe('StatusBadge', () => {
  it('names the status in text, not only by colour', () => {
    render(<StatusBadge status="delayed" />);
    expect(screen.getByText('Delayed')).toBeInTheDocument();
  });
});

describe('ProjectCard', () => {
  it('shows the staleness of the last capture', () => {
    renderWithProviders(<ProjectCard project={PROJECT} />);
    expect(screen.getByText(/hours ago|hour ago/i)).toBeInTheDocument();
  });

  it('links to the project by its code', () => {
    renderWithProviders(<ProjectCard project={PROJECT} />);
    expect(screen.getByRole('link', { name: PROJECT.name })).toHaveAttribute(
      'href',
      '/projects/NG_00',
    );
  });

  it('shows coordinates to six decimals', () => {
    renderWithProviders(<ProjectCard project={PROJECT} />);
    expect(screen.getByText('13.621800, 123.194800')).toBeInTheDocument();
  });
});

describe('CaptureStrip', () => {
  const capture: CaptureSummary = {
    id: 'i1',
    filename: 'NG_00_20260814T070000Z_001.jpg',
    captured_at: '2026-08-14T07:00:00Z',
    latitude: 13.6218,
    longitude: 123.1948,
    thumb_url: 'https://storage.example/thumb.jpg',
    status: 'inferred',
    map_url: 'https://maps.example/i1',
  };

  it('gives each capture descriptive alt text', () => {
    render(<CaptureStrip captures={[capture]} />);
    expect(screen.getByRole('img', { name: /site capture taken/i })).toBeInTheDocument();
  });

  it('degrades to a placeholder when no thumbnail URL was signed', () => {
    render(<CaptureStrip captures={[{ ...capture, thumb_url: null }]} />);
    expect(screen.getByText('No preview')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('says so plainly when a capture has no GPS fix', () => {
    render(<CaptureStrip captures={[{ ...capture, latitude: null, longitude: null }]} />);
    expect(screen.getByText('No GPS fix')).toBeInTheDocument();
  });

  it('shows an empty state rather than a blank area', () => {
    render(<CaptureStrip captures={[]} />);
    expect(screen.getByText(/no captures published yet/i)).toBeInTheDocument();
  });
});

describe('PrivateAccountNotice', () => {
  it('reveals the username and nothing else', () => {
    const { container } = render(<PrivateAccountNotice username="jrm" />);
    expect(screen.getByText('@jrm')).toBeInTheDocument();
    expect(screen.getByText('This account is private.')).toBeInTheDocument();
    // No project count, no join date, no avatar — two lines of text, total.
    expect(container.textContent).toBe('@jrmThis account is private.');
  });
});

describe('ProfilePage', () => {
  it('renders only the notice for a private account', async () => {
    vi.mocked(api.fetchProfile).mockResolvedValue({
      username: 'quiet',
      is_private: true,
      full_name: null,
      professional_role: null,
      company: null,
      bio: null,
    });

    renderWithProviders(
      <Routes>
        <Route path="/users/:username" element={<ProfilePage />} />
      </Routes>,
      '/users/quiet',
    );

    await waitFor(() => {
      expect(screen.getByText('This account is private.')).toBeInTheDocument();
    });
    expect(screen.queryByText(/public projects/i)).not.toBeInTheDocument();
  });
});

describe('ProjectPage', () => {
  it('renders a private or missing project as unavailable, not as an error', async () => {
    vi.mocked(api.fetchProject).mockRejectedValue(new ApiError('Project not found.', 404));

    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectCode" element={<ProjectPage />} />
      </Routes>,
      '/projects/SECRET_01',
    );

    await waitFor(() => {
      expect(screen.getByText(/this project is not available/i)).toBeInTheDocument();
    });
    // A visitor must not be able to tell "private" from "never existed".
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows a real failure as an error a visitor can act on', async () => {
    // 429 rather than 500: a 5xx is *deliberately* retried by the hook, so it
    // would still be loading when this assertion runs. A rate limit is a real
    // failure that is not retried, which is the branch under test.
    vi.mocked(api.fetchProject).mockRejectedValue(new ApiError('Too many requests.', 429));

    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectCode" element={<ProjectPage />} />
      </Routes>,
      '/projects/NG_00',
    );

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  it('does not link to a handler whose own profile is private', async () => {
    vi.mocked(api.fetchProject).mockResolvedValue({
      project_code: 'NG_00',
      name: 'Jollibee Naga Branch',
      intended_use: null,
      description: null,
      location_label: 'Naga City',
      latitude: 13.6218,
      longitude: 123.1948,
      map_url: 'https://maps.example/NG_00',
      osm_url: 'https://osm.example/NG_00',
      start_date: '2026-06-01',
      deadline_date: '2026-12-31',
      status: 'active',
      status_reason: 'On track.',
      progress_pct: 38.5,
      macro_stage: 'framing',
      stages: STAGES,
      handler_username: 'quiet',
      handler_name: null,
      handler_is_public: false,
      recent_images: [],
      remarks: [],
      timeline: [],
      last_capture_at: null,
    });

    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectCode" element={<ProjectPage />} />
      </Routes>,
      '/projects/NG_00',
    );

    await waitFor(() => {
      expect(screen.getByText('Jollibee Naga Branch')).toBeInTheDocument();
    });
    expect(screen.getByText('quiet')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'quiet' })).not.toBeInTheDocument();
  });
});
