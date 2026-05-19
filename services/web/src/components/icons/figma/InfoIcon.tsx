interface Props {
  className?: string;
}

// figma: 955:121744 — info icon used by the bulk download dialogs
// (modu-download + selected-shorts-download popups, nodes 1961:97387
// and 1961:97363). Navy-500 disc with a white "i" glyph rendered as
// a simple stem + dot.
export function InfoIcon({ className }: Props) {
  return (
    <svg
      className={className}
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="24" height="24" rx="12" fill="#234C77" />
      <path
        d="M12 6C12.5523 6 13 6.44772 13 7C13 7.55228 12.5523 8 12 8C11.4477 8 11 7.55228 11 7C11 6.44772 11.4477 6 12 6ZM12 10C12.5523 10 13 10.4477 13 11V17C13 17.5523 12.5523 18 12 18C11.4477 18 11 17.5523 11 17V11C11 10.4477 11.4477 10 12 10Z"
        fill="white"
      />
    </svg>
  );
}
