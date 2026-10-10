// icons.jsx — small, dependency-free icon set (feather-style outline icons).

function Icon({ children, size = 18, filled = false, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const LiveIcon       = (p) => <Icon {...p}><path d="M3 12h4l3-8 4 16 3-8h4" /></Icon>;
export const OrdersIcon     = (p) => <Icon {...p}><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></Icon>;
export const PositionsIcon  = (p) => <Icon {...p}><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></Icon>;
export const WatchlistsIcon = (p) => <Icon {...p}><path d="M6 3h12v18l-6-4-6 4z" /></Icon>;
export const AlertsIcon     = (p) => <Icon {...p}><path d="M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8" /><path d="M10 20a2 2 0 004 0" /></Icon>;
export const HistoryIcon    = (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>;
export const SettingsIcon   = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 005 15a1.65 1.65 0 00-1-1.51H3.91a2 2 0 010-4H4a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 5a1.65 1.65 0 001-1.51V3.4a2 2 0 014 0V4a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019 9a1.65 1.65 0 001.51 1H20.6a2 2 0 010 4h-.09A1.65 1.65 0 0019.4 15z" />
  </Icon>
);
export const ChartIcon      = (p) => <Icon size={15} {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" /></Icon>;
export const SearchIcon     = (p) => <Icon size={16} {...p}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></Icon>;
export const CloseIcon      = (p) => <Icon {...p}><path d="M6 6l12 12M18 6L6 18" /></Icon>;
export const SunIcon        = (p) => <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>;
export const MoonIcon       = (p) => <Icon {...p}><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" /></Icon>;
export const DownIcon       = (p) => <Icon {...p}><path d="M6 9l6 6 6-6" /></Icon>;
export const BookmarkIcon   = (p) => <Icon size={16} {...p}><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></Icon>;
export const EyeOffIcon     = (p) => (
  <Icon size={16} {...p}>
    <path d="M17.9 17.9A10 10 0 0112 19C7 19 2.7 15.8 1 12c.8-2 2.3-3.8 4.1-5.1M9.9 4.2A10 10 0 0112 4c5 0 9.3 3.2 11 7.9a10 10 0 01-1.9 3.4" />
    <path d="M14.1 14.1A3 3 0 019.9 9.9" />
    <path d="M3 3l18 18" />
  </Icon>
);

// Circular-arrow refresh / sync icon. Used for the topbar session-refresh button.
// Accepts className so the parent can attach the "spin" CSS animation while loading.
export const RefreshIcon = (p) => (
  <Icon {...p}>
    <path d="M23 4v6h-6" />
    <path d="M1 20v-6h6" />
    <path d="M3.5 9a9 9 0 0114.6-3.6L23 10M1 14l4.9 4.6A9 9 0 0020.5 15" />
  </Icon>
);

export const NAV_ICONS = {
  live:       LiveIcon,
  orders:     OrdersIcon,
  positions:  PositionsIcon,
  watchlists: WatchlistsIcon,
  alerts:     AlertsIcon,
  history:    HistoryIcon,
  ignored:    EyeOffIcon,
  settings:   SettingsIcon,
};
