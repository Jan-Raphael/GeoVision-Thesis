/**
 * The progress curve.
 *
 * In its own module on purpose: it is the only thing that imports Recharts,
 * which is roughly two thirds of the JavaScript this app ships. Keeping it
 * separate from the card components means the homepage — which renders cards
 * and no charts — never downloads a charting library to display a list.
 */

import { parseISO } from 'date-fns';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { EmptyState } from '@/components/common';
import { AI_CEILING_PCT } from '@/components/progress';
import type { TimelinePoint } from '@/lib/api';

/**
 * The progress curve.
 *
 * Two things are deliberate. Gaps are **not** interpolated — a window with no
 * captures is absent from the series, and joining across it would assert
 * measurements that were never taken. And the 80 % ceiling is drawn as a
 * reference line, so a curve that flattens there reads as "waiting for
 * inspection" rather than "stalled".
 */
export function TimelineChart({ points }: { points: TimelinePoint[] }) {
  if (points.length === 0) {
    return (
      <EmptyState
        title="No progress history yet"
        description="The chart appears once the site has been photographed and scored."
      />
    );
  }

  const data = points.map((point) => ({
    ...point,
    label: parseISO(point.window_start).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    }),
  }));

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <defs>
            <linearGradient id="gv-progress" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#1f5799" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#1f5799" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#64748b' }} tickLine={false} />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 11, fill: '#64748b' }}
            tickLine={false}
            axisLine={false}
            unit="%"
          />
          <ReferenceLine
            y={AI_CEILING_PCT}
            stroke="#b45309"
            strokeDasharray="4 4"
            label={{ value: 'AI ceiling', position: 'insideTopRight', fontSize: 10, fill: '#b45309' }}
          />
          <Tooltip
            formatter={(value) => [`${Number(value ?? 0).toFixed(1)}%`, 'Progress']}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
          />
          <Area
            type="monotone"
            dataKey="displayed_pct"
            stroke="#1f5799"
            strokeWidth={2}
            fill="url(#gv-progress)"
            // `connectNulls={false}` is the point: absent windows stay absent.
            connectNulls={false}
            dot={{ r: 2.5, fill: '#1f5799' }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
