/**
 * TanStack Query hooks over the public API.
 *
 * Query keys are declared in one place so a cache invalidation in Module 12
 * cannot miss a key by re-typing it slightly differently.
 *
 * A **404 is never retried**. The default retry policy exists for flaky
 * networks, and re-asking for a project that does not exist just makes a
 * visitor wait three times as long to be told so — and a private project
 * answers 404 by design, so this is the common path, not an edge case.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import {
  ApiError,
  fetchFeed,
  fetchProfile,
  fetchProject,
  search,
  type FeedFilters,
  type Page,
  type FeedProject,
  type PublicProfile,
  type PublicProject,
  type SearchResults,
} from '@/lib/api';

export const queryKeys = {
  feed: (filters: FeedFilters) => ['public', 'feed', filters] as const,
  project: (code: string) => ['public', 'project', code] as const,
  profile: (username: string) => ['public', 'profile', username] as const,
  search: (term: string) => ['public', 'search', term] as const,
};

/**
 * Retry transient failures only; a 404 is an answer, not a hiccup.
 *
 * The `error` parameter is typed `Error`, not `unknown`, and that matters more
 * than it looks: TanStack infers `TError` from this callback, so an `unknown`
 * here silently makes every hook's `error` unknown too, and every component
 * then has to narrow before reading `.message`.
 */
function retryUnlessClientError(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

export function useFeed(filters: FeedFilters = {}): UseQueryResult<Page<FeedProject>> {
  return useQuery({
    queryKey: queryKeys.feed(filters),
    queryFn: () => fetchFeed(filters),
    retry: retryUnlessClientError,
  });
}

export function useProject(code: string): UseQueryResult<PublicProject> {
  return useQuery({
    queryKey: queryKeys.project(code),
    queryFn: () => fetchProject(code),
    retry: retryUnlessClientError,
  });
}

export function useProfile(username: string): UseQueryResult<PublicProfile> {
  return useQuery({
    queryKey: queryKeys.profile(username),
    queryFn: () => fetchProfile(username),
    retry: retryUnlessClientError,
  });
}

/**
 * Search, disabled until the term is long enough for the server to accept it.
 *
 * The endpoint requires two characters and is rate-limited at 30/minute, so
 * firing on the first keystroke would spend the visitor's budget on queries
 * that can only fail.
 */
export function useSearch(term: string): UseQueryResult<SearchResults> {
  return useQuery({
    queryKey: queryKeys.search(term),
    queryFn: () => search(term),
    enabled: term.trim().length >= 2,
    retry: retryUnlessClientError,
  });
}
