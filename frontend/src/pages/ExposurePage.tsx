/**
 * Step 2 — how the concrete sits relative to the weather.
 *
 * This drives the IS 456 exposure class, which sets the minimum grade, cement
 * content and water/cement ratio everything downstream is judged against. It gets
 * its own page because it is the single input with the largest effect on the score,
 * and because five choices with real consequences deserve more than a dropdown.
 */
import { useNavigate } from 'react-router-dom';

import { PageShell } from '@/components/Shell';
import { Button, ChoiceCard, Popup } from '@/components/ui';
import { useSession } from '@/state/session-context';
import { ELEMENT_SITUATIONS } from '@/types/api';
import { useState } from 'react';

/** Consequence text, so a choice is made knowingly rather than guessed at. */
const CONSEQUENCE: Record<string, string> = {
  enclosed: 'Mildest case. The code allows the leanest mix here.',
  sheltered: 'Slightly stricter than enclosed.',
  exposed: 'The common case for outdoor structure, and the usual default.',
  buried: 'Soil holds moisture and salts against the concrete, so the code tightens.',
  tidal: 'The most severe class in IS 456. Expect a high grade and a low w/c ratio.',
};

export default function ExposurePage() {
  const { spec, update } = useSession();
  const navigate = useNavigate();
  const [explaining, setExplaining] = useState(false);

  return (
    <PageShell
      eyebrow="Step 2 of 5"
      title="How does the concrete sit?"
      lead={`For ${spec.district}. This decides which IS 456 exposure class applies, and that sets the minimum your specification has to clear.`}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {ELEMENT_SITUATIONS.map((situation) => (
          <ChoiceCard
            key={situation.value}
            label={situation.label}
            hint={situation.hint}
            selected={spec.situation === situation.value}
            onSelect={() => {
              update({ situation: situation.value });
            }}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={() => {
          setExplaining(true);
        }}
        className="mt-5 text-sm font-medium text-atmos underline underline-offset-4"
      >
        What difference does this make?
      </button>

      <div className="mt-10 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => {
            void navigate('/');
          }}
        >
          <span aria-hidden="true">←</span> Back
        </Button>
        <Button
          onClick={() => {
            void navigate('/mode');
          }}
        >
          Continue <span aria-hidden="true">→</span>
        </Button>
      </div>

      <Popup
        open={explaining}
        title="Why this question decides so much"
        description="IS 456:2000, Table 3 and Table 5."
        onClose={() => {
          setExplaining(false);
        }}
      >
        <p className="text-sm leading-relaxed text-ink-2">
          The code does not set one standard for all concrete. It sorts an element
          into an exposure class by how much water, salt and air reaches it, then
          sets a different minimum grade, minimum cement content and maximum
          water/cement ratio for each class.
        </p>
        <ul className="mt-4 space-y-2.5">
          {ELEMENT_SITUATIONS.map((situation) => (
            <li key={situation.value} className="text-sm">
              <span className="font-semibold text-ink-1">{situation.label}</span>
              <span className="text-ink-3"> — {CONSEQUENCE[situation.value] ?? ''}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs leading-relaxed text-ink-3">
          Your district&rsquo;s measured humidity, wet hours and distance from the coast
          are combined with this answer to pick the final class. You are not choosing
          the class directly.
        </p>
      </Popup>
    </PageShell>
  );
}
