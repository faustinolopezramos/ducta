// Vitest global setup — registers @testing-library/jest-dom matchers
// (toBeInTheDocument, toHaveClass, toBeDisabled, …) for the DOM assertions used
// across the component tests, and augments Vitest's `expect` types so the
// production `tsc -b` build type-checks them.
import "@testing-library/jest-dom/vitest";
