/**
 * @fileoverview Type definitions for page components
 * Provides type safety for page-level props and internal components
 */

import React from 'react';

// ═══════════════════════════════════════════════════════════════════════════
// WORKSPACE PAGE TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface SectionTitleProps {
  children: React.ReactNode;
  /** Optional count rendered as a subtle pill next to the title. */
  count?: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// SETTINGS PAGE TYPES
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// PIPELINE BUILDER TYPES
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// CONFIRM DIALOG TYPES
// ═══════════════════════════════════════════════════════════════════════════
