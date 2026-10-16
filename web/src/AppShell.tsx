import { useState } from 'react';
import App from './App';
import { Ledger } from './Ledger';

/** Review flow plus the expense ledger; saving a receipt refreshes the history. */
export default function AppShell() {
  const [refreshKey, setRefreshKey] = useState(0);
  return (
    <>
      <App onExpenseSaved={() => setRefreshKey(value => value + 1)} />
      <main className="ledger-page"><Ledger refreshKey={refreshKey} /></main>
    </>
  );
}
