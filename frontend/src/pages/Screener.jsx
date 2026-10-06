import ScreenerTable from "../components/ScreenerTable";

export default function Screener({
  rows,
  flashRowId,
  stockColors,
  ignoredSymbols,
  onIgnore,
  onWatchlistChanged,
  onNavigateWatchlists,
  settings,
  autoOrderSymbols,
  refetchAutoOrders,
}) {
  return (
    <ScreenerTable
      rows={rows}
      flashRowId={flashRowId}
      emptyMessage="No stocks have triggered today yet."
      stockColors={stockColors}
      ignoredSymbols={ignoredSymbols}
      onIgnore={onIgnore}
      onWatchlistChanged={onWatchlistChanged}
      onNavigateWatchlists={onNavigateWatchlists}
      settings={settings}
      autoOrderSymbols={autoOrderSymbols}
      refetchAutoOrders={refetchAutoOrders}
    />
  );
}
