/**
 * Small, generic hooks with no feature attachment.
 */

import { useEffect, useState } from 'react';

/**
 * Returns `value`, but only after it has stopped changing for `delayMs`.
 *
 * Search inputs wired straight to a query key (feed filters, the search page)
 * would otherwise fire one network request per keystroke — the request for
 * "N" is thrown away the instant "Ng" is typed, and again for "Ng_", and so
 * on. Debouncing the value the query key is derived from means a fast typist
 * costs one request, not one per character, while the input itself stays
 * perfectly responsive (it is never the debounced value that gets echoed
 * back into the field).
 */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delayMs]);

  return debounced;
}
