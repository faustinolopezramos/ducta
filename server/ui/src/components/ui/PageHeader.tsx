import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { IconArrowLeft } from "@tabler/icons-react";
import { Button } from "./Button";
import "./PageHeader.css";

export interface PageHeaderProps {
  title: string;
  description?: string;
  backTo?: string;
  backLabel?: string;
  actions?: ReactNode;
  /**
   * A tab strip belonging to this page. Rendered flush with the header's
   * bottom rule so the tabs read as part of the page's identity rather than as
   * a second, unrelated bar — which is how MLOps' own strip looked.
   */
  tabs?: ReactNode;
}

export function PageHeader({
  title,
  description,
  backTo,
  backLabel = "Back",
  actions,
  tabs,
}: PageHeaderProps) {
  const navigate = useNavigate();
  return (
    <header className={`page-header${tabs ? " page-header--tabbed" : ""}`}>
      {backTo && (
        <Button
          variant="ghost"
          size="sm"
          className="page-header__back"
          onClick={() => navigate(backTo)}
          leftIcon={<IconArrowLeft size={15} stroke={1.6} />}
        >
          {backLabel}
        </Button>
      )}
      <div className="page-header__content">
        <div className="page-header__copy">
          <h1 className="page-header__title">{title}</h1>
          {description && <p className="page-header__description">{description}</p>}
        </div>
        {actions && <div className="page-header__actions">{actions}</div>}
      </div>
      {tabs && <div className="page-header__tabs">{tabs}</div>}
    </header>
  );
}
