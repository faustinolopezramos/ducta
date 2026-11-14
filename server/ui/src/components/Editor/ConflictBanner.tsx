import { lazy, Suspense, useState } from "react";
import { IconAlertTriangle } from "@tabler/icons-react";
import type { FileConflict } from "./useFileSave";
import { defineDuctaTheme } from "./monacoSetup";

const DiffEditor = lazy(() => import("@monaco-editor/react").then((m) => ({ default: m.DiffEditor })));

/**
 * The file changed outside this editor since it was opened. Nothing was
 * overwritten: reload what is there now, compare the two, or keep this
 * editor's version on purpose.
 */
export function ConflictBanner({
  conflict,
  language,
  onReload,
  onKeepMine,
  busy,
}: {
  conflict: FileConflict;
  language: string;
  onReload: () => void;
  onKeepMine: () => void;
  busy?: boolean;
}) {
  const [comparing, setComparing] = useState(false);
  return (
    <div className="conflict" role="alert">
      <div className="conflict__bar">
        <IconAlertTriangle size={15} aria-hidden="true" />
        <span className="conflict__text">This file changed outside DUCTA since you opened it — your save was not written.</span>
        <button type="button" className="conflict__btn" onClick={onReload}>Reload theirs</button>
        <button type="button" className="conflict__btn" onClick={() => setComparing((v) => !v)} aria-expanded={comparing}>
          {comparing ? "Hide diff" : "View diff"}
        </button>
        <button type="button" className="conflict__btn is-danger" onClick={onKeepMine} disabled={busy}>Keep mine</button>
      </div>
      {comparing && (
        <div className="conflict__diff" aria-label="Theirs (left) and yours (right)">
          <Suspense fallback={null}>
            <DiffEditor
              original={conflict.theirs}
              modified={conflict.mine}
              language={language}
              theme={defineDuctaTheme(document.documentElement.getAttribute("data-theme") === "dark")}
              options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12, automaticLayout: true }}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}
