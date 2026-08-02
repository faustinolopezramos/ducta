import { Component } from "react";
import { colors, styles } from "../theme/tokens";
import Logger from "../utils/logger";
import { IconAlertCircle } from "@tabler/icons-react";

// ─────────────────────────────────────────────
// Enhanced Error Boundary Component
// - Catches React render errors
// - Provides recovery options
// - Logs to centralized logger
// - Shows user-friendly UI
// ─────────────────────────────────────────────

interface ErrorBoundaryProps {
  children: React.ReactNode;
  onError?: (error: Error, errorId: string) => void;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  errorId: string | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      errorId: null,
    };
  }

  static getDerivedStateFromError(_error: Error) {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const errorId = `error-${Date.now()}`;
    this.setState({
      error,
      errorInfo,
      errorId,
    });

    // Log to centralized logger
    Logger.error("React Error Boundary caught error", undefined, {
      message: error.message,
      stack: error.stack,
      componentStack: errorInfo.componentStack,
      errorId,
      timestamp: new Date().toISOString(),
    });

    // Optional: Send to error tracking service
    if (this.props.onError) {
      this.props.onError(error, errorId);
    }
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      errorId: null,
    });

    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  handleReload = () => {
    globalThis.location.reload();
  };

  handleGoHome = () => {
    globalThis.location.assign("/");
  };

  render() {
    if (this.state.hasError) {
      const isDev = import.meta.env.MODE === "development";

      return (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            background: colors.bg,
            padding: 20,
            fontFamily: styles.fontSans.fontFamily,
          }}
        >
          <div
            style={{
              maxWidth: 600,
              background: colors.surface,
              border: `2px solid ${colors.red}`,
              borderRadius: 12,
              padding: 40,
              textAlign: "center",
            }}
          >
            {/* Icon */}
            <div
              style={{
                fontSize: 64,
                marginBottom: 20,
                color: colors.red,
              }}
            >
              <IconAlertCircle size={64} />
            </div>

            {/* Title */}
            <h2
              style={{
                margin: "0 0 8px 0",
                fontSize: 24,
                fontWeight: 700,
                color: colors.text,
              }}
            >
              An unexpected error occurred
            </h2>

            {/* Message */}
            <p
              style={{
                margin: "0 0 20px 0",
                fontSize: 14,
                color: colors.textMuted,
                lineHeight: 1.6,
              }}
            >
              We encountered a problem rendering this screen. Use the following ID for support:
              <br />
              <code
                style={{
                  display: "inline-block",
                  margin: "8px 0 0 0",
                  padding: "8px 12px",
                  background: colors.bg,
                  borderRadius: 4,
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  color: colors.accent,
                }}
              >
                {this.state.errorId}
              </code>
            </p>

            {/* Error details (dev only) */}
            {isDev && this.state.error && (
              <details
                style={{
                  margin: "20px 0",
                  padding: "12px",
                  textAlign: "left",
                  background: colors.bg,
                  borderRadius: 6,
                  border: `1px solid ${colors.border}`,
                }}
              >
                <summary
                  style={{
                    cursor: "pointer",
                    fontWeight: 600,
                    color: colors.text,
                    marginBottom: 8,
                  }}
                >
                  Technical details (development only)
                </summary>
                <pre
                  style={{
                    margin: 0,
                    overflow: "auto",
                    maxHeight: 200,
                    fontSize: 11,
                    color: colors.textMuted,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {this.state.error.toString()}
                  {"\n\n"}
                  {this.state.errorInfo?.componentStack}
                </pre>
              </details>
            )}

            {/* Actions */}
            <div
              style={{
                display: "flex",
                gap: 12,
                justifyContent: "center",
                flexWrap: "wrap",
                marginTop: 24,
              }}
            >
              <button
                onClick={this.handleReset}
                style={{
                  padding: "10px 24px",
                  background: colors.accent,
                  border: "none",
                  borderRadius: 6,
                  color: colors.bgContrast,
                  cursor: "pointer",
                  fontWeight: 600,
                  fontSize: 14,
                  fontFamily: styles.fontSans.fontFamily,
                  transition: "opacity 0.2s",
                }}
                onMouseEnter={(e: React.MouseEvent<HTMLButtonElement>) => (e.currentTarget.style.opacity = "0.9")}
                onMouseLeave={(e: React.MouseEvent<HTMLButtonElement>) => (e.currentTarget.style.opacity = "1")}
              >
                Retry
              </button>
              <button
                onClick={this.handleReload}
                style={{
                  padding: "10px 24px",
                  background: colors.surface,
                  border: `1px solid ${colors.border}`,
                  borderRadius: 6,
                  color: colors.text,
                  cursor: "pointer",
                  fontWeight: 600,
                  fontSize: 14,
                  fontFamily: styles.fontSans.fontFamily,
                  transition: "opacity 0.2s",
                }}
                onMouseEnter={(e: React.MouseEvent<HTMLButtonElement>) => (e.currentTarget.style.opacity = "0.8")}
                onMouseLeave={(e: React.MouseEvent<HTMLButtonElement>) => (e.currentTarget.style.opacity = "1")}
              >
                Reload application
              </button>
              <button
                onClick={this.handleGoHome}
                style={{
                  padding: "10px 24px",
                  background: "transparent",
                  border: `1px dashed ${colors.border}`,
                  borderRadius: 6,
                  color: colors.textMuted,
                  cursor: "pointer",
                  fontWeight: 600,
                  fontSize: 14,
                  fontFamily: styles.fontSans.fontFamily,
                  transition: "opacity 0.2s",
                }}
                onMouseEnter={(e: React.MouseEvent<HTMLButtonElement>) => (e.currentTarget.style.opacity = "0.8")}
                onMouseLeave={(e: React.MouseEvent<HTMLButtonElement>) => (e.currentTarget.style.opacity = "1")}
              >
                Go to home
              </button>
            </div>

            {/* Help text */}
            <p
              style={{
                margin: "24px 0 0 0",
                fontSize: 12,
                color: colors.textMuted,
              }}
            >
              If the problem persists, share the ID with the support team.
            </p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

/**
 * HOC to wrap components with error boundary
 */
export function withErrorBoundary<P extends object>(Component: React.ComponentType<P>) {
  return function ErrorBoundaryWrapper(props: P) {
    return (
      <ErrorBoundary>
        <Component {...props} />
      </ErrorBoundary>
    );
  };
}
