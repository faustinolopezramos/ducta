import { IconCopy } from "@tabler/icons-react";
import { useToastStack } from "../../hooks/useModalStack";

/** Small copy-to-clipboard affordance for a hash/id shown elsewhere on the
 *  page — shared by the certificate modal, detail page, and standalone
 *  verify tool rather than redefined in each. */
export function CopyButton({ label, value }: Readonly<{ label: string; value: string }>) {
  const { show } = useToastStack();
  return (
    <button
      type="button"
      title={`Copy ${label}`}
      aria-label={`Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          show(`${label} copied`, "success");
        } catch {
          show(`Could not copy ${label}`, "error");
        }
      }}
      className="cert-copy-btn"
    >
      <IconCopy size={12} />
    </button>
  );
}
