'use client';

import { useMemo, useState } from 'react';
import type { Comparison, CommonHolding, FundBlock } from '@/lib/api';
import { formatMonth, pct } from '@/lib/api';

type SortKey = 'combined' | 'fund_a_pct' | 'fund_b_pct' | 'difference_pct' | 'company';

function FundCard({ fund, side }: { fund: FundBlock; side: 'A' | 'B' }) {
  return (
    <section className="card">
      <header>
        <span className="side">Fund {side}</span>
        <h3>{fund.name}</h3>
        <p className="meta">
          {fund.amc} · {fund.category ?? 'Category not disclosed'} ·{' '}
          {fund.management_style === 'PASSIVE' ? 'Passive' : 'Active'}
        </p>
      </header>
      <dl className="stats">
        <div>
          <dt>Total holdings</dt>
          <dd>{fund.holding_count}</dd>
        </div>
        <div>
          <dt>Top {Math.min(10, fund.holding_count)} total</dt>
          <dd>{pct(fund.top10_total_pct)}</dd>
        </div>
        <div>
          <dt>Equity allocation</dt>
          <dd>{pct(fund.equity_pct)}</dd>
        </div>
        <div>
          <dt>AUM (₹ crore)</dt>
          <dd>{fund.aum_crore === null ? '—' : Number(fund.aum_crore).toLocaleString('en-IN')}</dd>
        </div>
      </dl>
      <table>
        <caption>
          Top {Math.min(10, fund.holding_count)} holdings
          {fund.holding_count < 10 && ` (this fund holds only ${fund.holding_count})`}
        </caption>
        <thead>
          <tr>
            <th scope="col">Company</th>
            <th scope="col">Industry</th>
            <th scope="col" className="num">
              % to NAV
            </th>
          </tr>
        </thead>
        <tbody>
          {fund.top10.map((holding) => (
            <tr key={holding.company}>
              <td>{holding.company}</td>
              <td className="muted">{holding.industry ?? '—'}</td>
              <td className="num">{pct(holding.weight_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function ComparisonView({ result }: { result: Comparison }) {
  const [sort, setSort] = useState<SortKey>('combined');
  const [descending, setDescending] = useState(true);
  const { fund_a: a, fund_b: b, comparison: c } = result;

  const rows = useMemo(() => {
    const value = (row: CommonHolding): number | string => {
      if (sort === 'company') return row.company;
      if (sort === 'combined') return Number(row.fund_a_pct) + Number(row.fund_b_pct);
      if (sort === 'difference_pct') return Math.abs(Number(row.difference_pct));
      return Number(row[sort]);
    };
    return [...result.common_holdings].sort((x, y) => {
      const left = value(x);
      const right = value(y);
      const order = typeof left === 'string' ? left.localeCompare(right as string) : left - (right as number);
      return descending ? -order : order;
    });
  }, [result.common_holdings, sort, descending]);

  const sortBy = (key: SortKey) => {
    if (key === sort) setDescending((current) => !current);
    else {
      setSort(key);
      setDescending(key !== 'company');
    }
  };

  const headers: [SortKey, string][] = [
    ['company', 'Company'],
    ['fund_a_pct', `${a.name} %`],
    ['fund_b_pct', `${b.name} %`],
    ['difference_pct', 'Difference'],
  ];

  return (
    <div className="results">
      <p className="asof">
        Both portfolios as on <strong>{formatMonth(result.as_of_date)}</strong> — the latest month both
        funds disclose.
      </p>

      <div className="cards">
        <FundCard fund={a} side="A" />
        <FundCard fund={b} side="B" />
      </div>

      <section className="overlap">
        <h2>Overlap</h2>
        <div className="metrics">
          <div className="metric">
            <span className="value">{pct(c.a_top10_in_b_pct)}</span>
            <span className="label">
              Fund A’s top 10 represented in Fund B’s full portfolio
            </span>
          </div>
          <div className="metric">
            <span className="value">{pct(c.b_top10_in_a_pct)}</span>
            <span className="label">
              Fund B’s top 10 represented in Fund A’s full portfolio
            </span>
          </div>
          <div className="metric">
            <span className="value">{pct(c.common_weight_a_pct)}</span>
            <span className="label">All common stocks as a share of Fund A</span>
          </div>
          <div className="metric">
            <span className="value">{pct(c.common_weight_b_pct)}</span>
            <span className="label">All common stocks as a share of Fund B</span>
          </div>
        </div>
        <p className="counts">
          <strong>{c.common_security_count}</strong> common stocks · {result.unique_to_a_count} unique to
          Fund A · {result.unique_to_b_count} unique to Fund B · symmetric weighted overlap{' '}
          {pct(c.symmetric_weighted_overlap_pct)}
        </p>
      </section>

      {result.explanation && (
        <section className="explanation">
          <h2>Summary</h2>
          <p>{result.explanation}</p>
          <p className="note">
            Generated commentary. Every percentage above is computed from the stored portfolios, not
            from the language model.
          </p>
        </section>
      )}
      {result.explanation_status === 'UNAVAILABLE' && (
        <p className="note">Commentary unavailable — no Gemini key configured. All figures are unaffected.</p>
      )}
      {result.explanation_status === 'WITHHELD' && (
        <p className="note">Commentary withheld because it restated figures. All figures are unaffected.</p>
      )}

      <section className="common">
        <h2>Common holdings ({c.common_security_count})</h2>
        {rows.length === 0 ? (
          <p className="note">These two portfolios share no equity holdings this month.</p>
        ) : (
          <table>
            <thead>
              <tr>
                {headers.map(([key, title]) => (
                  <th
                    key={key}
                    scope="col"
                    className={key === 'company' ? '' : 'num'}
                    aria-sort={sort === key ? (descending ? 'descending' : 'ascending') : 'none'}
                  >
                    <button type="button" onClick={() => sortBy(key)}>
                      {title}
                      {sort === key && <span aria-hidden>{descending ? ' ▾' : ' ▴'}</span>}
                    </button>
                  </th>
                ))}
                <th scope="col">Industry</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.security_id}>
                  <td>{row.company}</td>
                  <td className="num">{pct(row.fund_a_pct)}</td>
                  <td className="num">{pct(row.fund_b_pct)}</td>
                  <td className={`num ${Number(row.difference_pct) >= 0 ? 'up' : 'down'}`}>
                    {Number(row.difference_pct) > 0 ? '+' : ''}
                    {Number(row.difference_pct).toFixed(2)}
                  </td>
                  <td className="muted">{row.industry ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
