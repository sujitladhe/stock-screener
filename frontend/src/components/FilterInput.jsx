import { SearchIcon, CloseIcon } from "../icons";

/**
 * A "type to filter the table" box -- same look as StockSearchInput
 * (icon + clear button) but no dropdown, since it narrows what's
 * already on screen instead of picking one stock to act on.
 */
export default function FilterInput({ value, onChange, placeholder }) {
  return (
    <div className="ss">
      <span className="ss-icon"><SearchIcon /></span>
      <input
        className="input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={placeholder}
      />
      {value && (
        <button type="button" className="ss-clear" aria-label="Clear search" onClick={() => onChange("")}>
          <CloseIcon size={14} />
        </button>
      )}
    </div>
  );
}
