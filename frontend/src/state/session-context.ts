/**
 * The session's shape and its accessor hook.
 *
 * Split from the provider because a module that exports both a component and a
 * hook defeats React Fast Refresh — editing the provider would remount the whole
 * tree and discard the answers collected so far, which is exactly what this state
 * exists to prevent.
 */
import { createContext, useContext } from 'react';

import type { ConcreteMixInput, DistrictList, ElementSituation } from '@/types/api';

export interface SiteSpecification {
  district: string;
  situation: ElementSituation;
  concrete: ConcreteMixInput;
  wallingMaterialId: string;
  /** True = score what I chose. False = tell me what to use. */
  evaluateOwnMaterials: boolean;
}

/** A site boundary drawn on the globe, in WGS84 degrees. */
export interface Area {
  south: number;
  north: number;
  west: number;
  east: number;
}

export interface SessionValue {
  spec: SiteSpecification;
  update: (patch: Partial<SiteSpecification>) => void;
  updateConcrete: (patch: Partial<ConcreteMixInput>) => void;
  reset: () => void;
  /**
   * The drawn site boundary, when the user picked by dragging rather than by name.
   *
   * Kept beside the specification rather than inside it because the two lead to
   * different endpoints: an area scores through `/score/area`, which reports how
   * its climate was derived, while a named district scores through `/score`, whose
   * reading is measured directly. Exactly one of `spec.district` and `area` is set.
   */
  area: Area | null;
  setArea: (area: Area | null) => void;
  districts: DistrictList | null;
  districtsError: unknown;
}

export const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (value === null) {
    // A hard failure rather than a default: a silently empty session would show a
    // score computed from placeholder inputs, which is the one thing this product
    // must never do.
    throw new Error('useSession must be used inside <SessionProvider>.');
  }
  return value;
}
