/**
 * The public application: router, query client, routes.
 *
 * Every route here is reachable without an account — Module 11 is spec section
 * A in full. The authenticated routes mount alongside these in Module 12.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { Suspense, lazy } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { PublicLayout } from '@/app/layout';
import { SkeletonGrid } from '@/components/common';
import { RequireAuth, SessionProvider } from '@/features/auth/session';
import { createQueryClient } from '@/lib/query-client';
import { LoginPage, RegisterPage } from '@/pages/auth';
import { FeedPage } from '@/pages/feed';
import { NotFoundPage } from '@/pages/misc';

/**
 * Everything except the homepage is loaded on demand.
 *
 * The project page pulls in Recharts, which is roughly two thirds of the
 * bundle on its own. Making the first paint of the *homepage* wait for a chart
 * library it never renders is the difference between a fast feed and a slow
 * one, and the feed is what a visitor lands on.
 */
const ProjectPage = lazy(() =>
  import('@/pages/project').then((module) => ({ default: module.ProjectPage })),
);
const ProfilePage = lazy(() =>
  import('@/pages/misc').then((module) => ({ default: module.ProfilePage })),
);
const SearchPage = lazy(() =>
  import('@/pages/misc').then((module) => ({ default: module.SearchPage })),
);
const ContactPage = lazy(() =>
  import('@/pages/misc').then((module) => ({ default: module.ContactPage })),
);
// The owner surface is a separate chunk: a visitor browsing public projects
// never downloads the dashboard they cannot sign in to.
const MePage = lazy(() => import('@/pages/me').then((module) => ({ default: module.MePage })));
const CreateProjectPage = lazy(() =>
  import('@/pages/me').then((module) => ({ default: module.CreateProjectPage })),
);
const ManageProjectPage = lazy(() =>
  import('@/pages/manage').then((module) => ({ default: module.ManageProjectPage })),
);

function Deferred({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<SkeletonGrid count={1} />}>{children}</Suspense>;
}

/** The route table, exported so tests can mount it under a memory router. */
export function PublicRoutes() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route index element={<FeedPage />} />
        <Route
          path="projects/:projectCode"
          element={
            <Suspense fallback={<SkeletonGrid count={1} />}>
              <ProjectPage />
            </Suspense>
          }
        />
        <Route
          path="users/:username"
          element={
            <Suspense fallback={<SkeletonGrid count={1} />}>
              <ProfilePage />
            </Suspense>
          }
        />
        <Route
          path="search"
          element={
            <Suspense fallback={<SkeletonGrid count={2} />}>
              <SearchPage />
            </Suspense>
          }
        />
        <Route
          path="contact"
          element={
            <Suspense fallback={<SkeletonGrid count={1} />}>
              <ContactPage />
            </Suspense>
          }
        />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />

        <Route element={<RequireAuth />}>
          <Route path="me" element={<Deferred><MePage /></Deferred>} />
          <Route path="projects/new" element={<Deferred><CreateProjectPage /></Deferred>} />
          <Route
            path="projects/:projectId/manage"
            element={<Deferred><ManageProjectPage /></Deferred>}
          />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={createQueryClient()}>
      <BrowserRouter>
        <SessionProvider>
          <PublicRoutes />
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
