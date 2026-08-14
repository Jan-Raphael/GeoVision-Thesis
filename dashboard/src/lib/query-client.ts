/**
 * The app-wide query client.
 *
 * Separate from the component module so React Fast Refresh keeps working: a
 * file that exports both components and helpers loses hot reloading for the
 * whole file.
 *
 * `staleTime` is a minute because construction progress moves in hours, not
 * seconds — refetching on every window focus would spend a visitor's bandwidth
 * redrawing an identical page. Retries are decided per query in `queries.ts`,
 * where a 404 can be told apart from a flaky network.
 */

import { QueryClient } from '@tanstack/react-query';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
      },
    },
  });
}
