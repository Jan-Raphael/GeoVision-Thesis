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
import { createQueryClient } from '@/lib/query-client';
import { FeedPage } from '@/pages/feed';
import { AuthPlaceholderPage, NotFoundPage } from '@/pages/misc';

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
        <Route path="login" element={<AuthPlaceholderPage mode="login" />} />
        <Route path="register" element={<AuthPlaceholderPage mode="register" />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={createQueryClient()}>
      <BrowserRouter>
        <PublicRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
