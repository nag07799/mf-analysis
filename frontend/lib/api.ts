export const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export type Fund = {
  scheme_id: number;
  amc: string;
  scheme_name: string;
  category: string | null;
  management_style: string | null;
};

export type TopHolding = { company: string; industry: string | null; weight_pct: string };

export type FundBlock = {
  scheme_id: number;
  name: string;
  amc: string;
  category: string | null;
  management_style: string | null;
  holding_count: number;
  top10_total_pct: string;
  top10: TopHolding[];
  equity_pct: string | null;
  aum_crore: string | null;
  validation_status: string;
  complete_holdings: boolean;
};

export type CommonHolding = {
  security_id: number;
  company: string;
  industry: string | null;
  isin: string | null;
  fund_a_pct: string;
  fund_b_pct: string;
  difference_pct: string;
};

export type Comparison = {
  as_of_date: string;
  fund_a: FundBlock;
  fund_b: FundBlock;
  comparison: {
    a_top10_in_b_pct: string;
    b_top10_in_a_pct: string;
    common_security_count: number;
    common_weight_a_pct: string;
    common_weight_b_pct: string;
    symmetric_weighted_overlap_pct: string;
  };
  common_holdings: CommonHolding[];
  unique_to_a_count: number;
  unique_to_b_count: number;
  explanation: string | null;
  explanation_status: string;
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const fetchFunds = (query: string) =>
  get<{ funds: Fund[] }>(`/api/v1/funds?limit=1000${query ? `&q=${encodeURIComponent(query)}` : ''}`);

/** Section 37: the month list for a pair is the intersection, never a silent mix. */
export const fetchMonths = (ids: number[]) =>
  get<{ months: string[]; latest_common_month: string | null }>(
    `/api/v1/months${ids.length ? `?${ids.map((i) => `scheme_ids=${i}`).join('&')}` : ''}`,
  );

export const fetchComparison = (a: number, b: number, month: string | null, explain: boolean) =>
  get<Comparison>(
    `/api/v1/compare?fund_a_id=${a}&fund_b_id=${b}` +
      `${month ? `&as_of_date=${month}` : ''}${explain ? '&explain=true' : ''}`,
  );

export const formatMonth = (value: string) =>
  new Date(value).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });

export const pct = (value: string | null) => (value === null ? '—' : `${Number(value).toFixed(2)}%`);
