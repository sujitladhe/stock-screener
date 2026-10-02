import ScreenerTable from "../components/ScreenerTable";

export default function Screener({ rows, flashRowId, stockColors, onWatchlistChanged, onNavigateWatchlists, settings }) {
  return (
    <ScreenerTable
      rows={rows}
      flashRowId={flashRowId}
      emptyMessage="No stocks have triggered today yet."
      stockColors={stockColors}
      onWatchlistChanged={onWatchlistChanged}
      onNavigateWatchlists={onNavigateWatchlists}
      settings={settings}
    />
  );
}
