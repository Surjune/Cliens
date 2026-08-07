/**
 * Per-component material selection.
 *
 * Each option shows its published source, because an undocumented resistance
 * rating is not something a reader should be asked to trust in a permit context.
 */
import { formatComponent } from '@/lib/format';
import {
  BUILDING_COMPONENTS,
  type BuildingComponent,
  type MaterialCatalogue,
  type MaterialSelection,
} from '@/types/api';

export function MaterialPicker({
  catalogue,
  selection,
  onChange,
}: {
  catalogue: MaterialCatalogue;
  selection: Partial<MaterialSelection>;
  onChange: (component: BuildingComponent, code: string) => void;
}) {
  return (
    <div className="space-y-4">
      {BUILDING_COMPONENTS.map((component) => {
        const options = catalogue[component];
        const chosen = selection[component];
        const detail = options.find((option) => option.code === chosen);

        return (
          <div key={component}>
            <label
              htmlFor={`material-${component}`}
              className="block text-sm font-medium text-slate-700"
            >
              {formatComponent(component)}
            </label>
            <select
              id={`material-${component}`}
              value={chosen ?? ''}
              onChange={(event) => {
                onChange(component, event.target.value);
              }}
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="" disabled>
                Choose a material…
              </option>
              {options.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.name}
                </option>
              ))}
            </select>

            {detail !== undefined && (
              <details className="mt-1.5">
                <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                  Resistance: wind {detail.resistance.wind.toFixed(2)} · flood{' '}
                  {detail.resistance.flood.toFixed(2)} · heat {detail.resistance.heat.toFixed(2)}
                </summary>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">
                  <span className="font-medium">Source:</span> {detail.source_reference}
                </p>
                {detail.notes !== null && detail.notes !== undefined && (
                  <p className="mt-1 text-xs leading-relaxed text-slate-500">{detail.notes}</p>
                )}
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
