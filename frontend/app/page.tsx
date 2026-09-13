'use client';

import { useEffect, useState } from 'react';
import FundSelector from '@/components/FundSelector';
import ComparisonView from '@/components/ComparisonView';
import { fetchComparison, fetchFunds, fetchMonths, formatMonth } from '@/lib/api';
import type { Comparison, Fund } from '@/lib/api';

export default function Page() {
  const [funds, setFunds] = useState<Fund[]>([]);
  const [fundA, setFundA] = useState<number | null>(null);
  const [fundB, setFundB] = useState<number | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [month, setMonth] = useState<string>('');
  const [result, setResult] = useState<Comparison | null>(null);
  const [explain, setExplain] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchFunds('')
      .then((data) => setFunds(data.funds))
      .catch((exc: Error) => setError(exc.message));
  }, []);

  // The month list is always the intersection for the current pair (section 37).
  useEffect(() => {
    const ids = [fundA, fundB].filter((id): id is number => id !== null);
    fetchMonths(ids)
      .then((data) => {
        setMonths(data.months);
        setMonth((current) =>
          current && data.months.includes(current) ? current : data.latest_common_month ?? '',
        );
      })
      .catch((exc: Error) => setError(exc.message));
  }, [fundA, fundB]);

  const compare = async () => {
    if (fundA === null || fundB === null) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await fetchComparison(fundA, fundB, month || null, explain));
    } catch (exc) {
      setResult(null);
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const ready = fundA !== null && fundB !== null;

  return (
    <main>
      <header className="masthead">
        <h1>Indian Equity Mutual Fund Overlap</h1>
        <p>
          Portfolio overlap between any two equity schemes, computed from official monthly factsheets
          and portfolio disclosures.
        </p>
      </header>

      <form
        className="controls"
        onSubmit={(event) => {
          event.preventDefault();
          void compare();
        }}
      >
        <div className="field">
          <label htmlFor="month">Factsheet month</label>
          <select id="month" value={month} onChange={(event) => setMonth(event.target.value)}>
            {months.length === 0 && <option value="">No common month available</option>}
            {months.map((value, index) => (
              <option key={value} value={value}>
                {formatMonth(value)}
                {index === 0 && ready ? ' — latest common month' : ''}
              </option>
            ))}
          </select>
        </div>

        <FundSelector label="Fund A" funds={funds} value={fundA} exclude={fundB} onChange={setFundA} />
        <FundSelector label="Fund B" funds={funds} value={fundB} exclude={fundA} onChange={setFundB} />

        <div className="actions">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={explain}
              onChange={(event) => setExplain(event.target.checked)}
            />
            Add written summary
          </label>
          <button type="submit" disabled={!ready || busy || !month}>
            {busy ? 'Comparing…' : 'Compare'}
          </button>
        </div>
      </form>

      {error && <p className="error">{error}</p>}
      {funds.length === 0 && !error && <p className="note">Loading the equity fund universe…</p>}
      {result && <ComparisonView result={result} />}
    </main>
  );
}
