"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { setLevelColor, type Level } from "@/lib/api/curriculum";
import { LEVEL_COLOR_PRESETS, levelColorName, levelSwatch } from "@/lib/level-color";

const HEX = /^#[0-9a-f]{6}$/i;

/**
 * The level's colour ("I'm blue now"): a preset, a custom hex, or back to the
 * default for its number. The label colour on it is picked for AA contrast.
 */
export function LevelColorPicker({ level, onSaved }: { level: Level; onSaved: () => void }) {
  const [custom, setCustom] = useState(level.display_color);
  const save = useMutation({
    mutationFn: (color: string) => setLevelColor(level.level_id, color),
    onSuccess: (saved) => {
      setCustom(saved.display_color);
      onSaved();
    },
  });
  const swatch = levelSwatch(level.display_color);
  const inputId = `level-color-${level.level_id}`;

  return (
    <div className="space-y-2 px-4 py-3" data-testid="level-color-picker">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-rally-ink">Colour</span>
        <span
          className="rounded-full px-3 py-1 text-sm font-bold"
          style={{ background: swatch.fill, color: swatch.on }}
        >
          Level {level.sequence} · {levelColorName(level.display_color) ?? "Custom"}
        </span>
        {level.color && (
          <button
            type="button"
            disabled={save.isPending}
            onClick={() => save.mutate("")}
            className="min-h-touch px-1 text-sm font-bold text-rally-cobalt-700 disabled:opacity-50"
          >
            Use default
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {LEVEL_COLOR_PRESETS.map((p) => {
          const active = p.hex.toLowerCase() === level.display_color.toLowerCase();
          return (
            <button
              key={p.hex}
              type="button"
              aria-label={p.name}
              aria-pressed={active}
              disabled={save.isPending}
              onClick={() => save.mutate(p.hex)}
              className={`h-11 w-11 rounded-full ring-1 ring-black/25 ${
                active ? "outline outline-[3px] outline-offset-2 outline-rally-ink" : ""
              }`}
              style={{ background: p.hex }}
            />
          );
        })}
        <label htmlFor={inputId} className="ml-1 text-xs font-bold text-status-slate-600">
          Custom hex
        </label>
        <input
          id={inputId}
          value={custom}
          onChange={(e) => setCustom(e.target.value.trim())}
          placeholder="#2563EB"
          className="min-h-touch w-28 rounded-md border-2 border-rally-line px-2 text-sm"
        />
        <button
          type="button"
          disabled={!HEX.test(custom) || save.isPending}
          onClick={() => save.mutate(custom)}
          className="min-h-touch rounded-md border-2 border-rally-line px-3 text-sm font-bold disabled:opacity-40"
        >
          Save
        </button>
      </div>
      {save.isError && (
        <p role="alert" className="text-xs text-red-700">
          Couldn&apos;t save the colour.
        </p>
      )}
    </div>
  );
}
