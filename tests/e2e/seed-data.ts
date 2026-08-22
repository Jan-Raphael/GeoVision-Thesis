/**
 * The fixed, known values `scripts/seed_db.py` produces.
 *
 * Kept in one file rather than repeated per spec, so a change to the seed
 * script (a renamed project, a different password) is a one-line fix here
 * instead of a search-and-replace across every journey.
 */
export const SEEDED_USER = {
  username: 'carla_owner',
  password: 'geovision-dev',
} as const;

export const SEEDED_PUBLIC_PROJECT = {
  name: 'Jollibee Branch - Naga',
  code: 'NG_00',
} as const;

export const SEEDED_PRIVATE_PROJECT = {
  name: 'Confidential Warehouse Expansion',
  code: 'WH_07',
} as const;
