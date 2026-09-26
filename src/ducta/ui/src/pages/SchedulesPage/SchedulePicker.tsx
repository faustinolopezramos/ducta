import { useState } from "react";
import { IconCalendar, IconClock } from "@tabler/icons-react";
import {
  buildCron,
  computeNextRun,
  describeCron,
  parseCronForBuilder,
  validateCron,
  type CronBuilderState,
  type CronFrequency,
} from "../../utils/cron";
import { formatUtc } from "../../utils/timeLabels";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => i + 1);

const pad2 = (n: number): string => n.toString().padStart(2, "0");

const DEFAULT_BUILDER: CronBuilderState = {
  frequency: "daily",
  hour: 0,
  minute: 0,
  weekdays: [1],
  dayOfMonth: 1,
};

/**
 * Calendar (weekday / day-of-month pills) + clock (native time input) editor
 * for the common recurring shapes — daily / weekly / monthly — that feeds the
 * "Cron expression (5 fields, UTC)" field. Not every cron is representable
 * this way (steps, ranges, multiple days of month, a specific month), so an
 * "Advanced" escape hatch keeps raw editing available; switching between the
 * two never discards the other mode's value, only which one is currently
 * driving `cron`.
 */
export function SchedulePicker({
  cron,
  onChange,
}: Readonly<{ cron: string; onChange: (cron: string) => void }>) {
  const initialBuilder = parseCronForBuilder(cron) ?? DEFAULT_BUILDER;
  const [advanced, setAdvanced] = useState(!parseCronForBuilder(cron));
  const [rawCron, setRawCron] = useState(cron);
  const [builder, setBuilder] = useState<CronBuilderState>(initialBuilder);

  const updateBuilder = (patch: Partial<CronBuilderState>) => {
    const next = { ...builder, ...patch };
    setBuilder(next);
    onChange(buildCron(next));
  };

  const toggleWeekday = (day: number) => {
    const next = builder.weekdays.includes(day)
      ? builder.weekdays.filter((d) => d !== day)
      : [...builder.weekdays, day];
    updateBuilder({ weekdays: next });
  };

  const switchToAdvanced = () => {
    setRawCron(cron);
    setAdvanced(true);
  };

  const switchToBuilder = () => {
    const parsed = parseCronForBuilder(rawCron);
    if (parsed) {
      setBuilder(parsed);
      onChange(rawCron);
    } else {
      onChange(buildCron(builder));
    }
    setAdvanced(false);
  };

  const cronError = validateCron(cron);
  const nextRun = !cronError ? computeNextRun(cron, new Date()) : null;

  return (
    <div className="schedule-picker">
      <div className="schedule-picker__modes">
        <button
          type="button"
          className="schedule-mode-tab"
          aria-pressed={!advanced}
          onClick={switchToBuilder}
        >
          <IconCalendar size={13} /> Calendar &amp; clock
        </button>
        <button
          type="button"
          className="schedule-mode-tab"
          aria-pressed={advanced}
          onClick={switchToAdvanced}
        >
          Advanced (raw cron)
        </button>
      </div>

      {advanced ? (
        <>
          <label className="projects-modal__label" htmlFor="schedule-cron" style={{ marginTop: 10 }}>
            Cron expression (5 fields, UTC)
          </label>
          <input
            id="schedule-cron"
            className="projects-modal__input"
            value={rawCron}
            onChange={(e) => {
              setRawCron(e.target.value);
              onChange(e.target.value);
            }}
            placeholder="0 0 * * *"
            aria-invalid={!!cronError}
          />
        </>
      ) : (
        <>
          <div className="schedule-freq-pills" role="group" aria-label="Repeat frequency">
            {(["daily", "weekly", "monthly"] as CronFrequency[]).map((freq) => (
              <button
                key={freq}
                type="button"
                className="schedule-freq-pill"
                aria-pressed={builder.frequency === freq}
                onClick={() => updateBuilder({ frequency: freq })}
              >
                {freq === "daily" ? "Every day" : freq === "weekly" ? "Every week" : "Every month"}
              </button>
            ))}
          </div>

          {builder.frequency === "weekly" && (
            <div className="schedule-weekday-picker" role="group" aria-label="Days of the week">
              {WEEKDAY_LABELS.map((label, day) => (
                <button
                  key={label}
                  type="button"
                  className="schedule-weekday-pill"
                  aria-pressed={builder.weekdays.includes(day)}
                  onClick={() => toggleWeekday(day)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {builder.frequency === "monthly" && (
            <div className="schedule-daygrid" role="group" aria-label="Day of the month">
              {DAYS_OF_MONTH.map((day) => (
                <button
                  key={day}
                  type="button"
                  className="schedule-day-cell"
                  aria-pressed={builder.dayOfMonth === day}
                  onClick={() => updateBuilder({ dayOfMonth: day })}
                >
                  {day}
                </button>
              ))}
            </div>
          )}

          <label className="projects-modal__label schedule-clock-label" htmlFor="schedule-time" style={{ marginTop: 12 }}>
            <IconClock size={13} /> Time (UTC)
          </label>
          <input
            id="schedule-time"
            type="time"
            className="projects-modal__input schedule-clock-input"
            value={`${pad2(builder.hour)}:${pad2(builder.minute)}`}
            onChange={(e) => {
              const [h, m] = e.target.value.split(":").map(Number);
              if (Number.isInteger(h) && Number.isInteger(m)) {
                updateBuilder({ hour: h, minute: m });
              }
            }}
          />
        </>
      )}

      {cronError ? (
        <p className="projects-modal__hint schedule-form__error">{cronError}</p>
      ) : (
        <p className="projects-modal__hint">
          <code>{cron}</code> — {describeCron(cron)}
          {nextRun && <> — next run {formatUtc(nextRun.toISOString())}</>}
        </p>
      )}
    </div>
  );
}
