'use client';

import { useMemo, useState } from 'react';
import type { Fund } from '@/lib/api';

type Props = {
  label: string;
  funds: Fund[];
  value: number | null;
  exclude: number | null;
  onChange: (id: number | null) => void;
};

/** Searchable selector showing AMC | Scheme | Category | Active/Passive. */
export default function FundSelector({ label, funds, value, exclude, onChange }: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

  const selected = funds.find((f) => f.scheme_id === value) ?? null;
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return funds
      .filter((f) => f.scheme_id !== exclude)
      .filter((f) =>
        !needle ||
        `${f.amc} ${f.scheme_name} ${f.category ?? ''}`.toLowerCase().includes(needle),
      )
      .slice(0, 80);
  }, [funds, query, exclude]);

  return (
    <div className="field">
      <label htmlFor={`${label}-search`}>{label}</label>
      <div className="combo">
        <input
          id={`${label}-search`}
          type="search"
          autoComplete="off"
          placeholder={selected ? selected.scheme_name : 'Search equity funds…'}
          value={open ? query : selected?.scheme_name ?? ''}
          onFocus={() => {
            setOpen(true);
            setQuery('');
          }}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onChange={(event) => setQuery(event.target.value)}
        />
        {selected && !open && (
          <button type="button" className="clear" aria-label="Clear" onClick={() => onChange(null)}>
            ×
          </button>
        )}
        {open && (
          <ul className="options" role="listbox">
            {matches.length === 0 && <li className="empty">No equity fund matches that search.</li>}
            {matches.map((fund) => (
              <li key={fund.scheme_id}>
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    onChange(fund.scheme_id);
                    setOpen(false);
                  }}
                >
                  <span className="amc">{fund.amc.replace(' Mutual Fund', '')}</span>
                  <span className="name">{fund.scheme_name}</span>
                  <span className="meta">
                    {fund.category ?? 'Category not disclosed'} ·{' '}
                    {fund.management_style === 'PASSIVE' ? 'Passive' : 'Active'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {selected && (
        <p className="hint">
          {selected.amc} · {selected.category ?? 'Category not disclosed'} ·{' '}
          {selected.management_style === 'PASSIVE' ? 'Passive' : 'Active'}
        </p>
      )}
    </div>
  );
}
