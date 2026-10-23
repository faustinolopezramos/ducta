import { describe, expect, it } from "vitest";
import type { RunTableRow } from "../../api/mlopsApi";
import { columnLabel, rowToRun, runTableToCsv } from "./runTable";

const row = (extra: Record<string, unknown> = {}): RunTableRow => ({
  run_id: "r1",
  pipeline: "churn",
  run_name: "churn-1",
  status: "COMPLETED",
  param_max_depth: 6,
  metric_val_auc: 0.91,
  ...extra,
});

describe("columnLabel", () => {
  it("names a hyperparameter or a metric by its own name", () => {
    expect(columnLabel("param_max_depth")).toBe("max_depth");
    expect(columnLabel("metric_val_auc")).toBe("val_auc");
    expect(columnLabel("run_name")).toBe("run_name");
  });
});

describe("runTableToCsv", () => {
  it("writes the header, then one line per run, in column order", () => {
    const csv = runTableToCsv(["run_id", "param_max_depth", "metric_val_auc"], [row()]);
    expect(csv).toBe("run_id,param_max_depth,metric_val_auc\r\nr1,6,0.91\r\n");
  });

  it("leaves a missing value empty", () => {
    const csv = runTableToCsv(["run_id", "model_name"], [row()]);
    expect(csv).toBe("run_id,model_name\r\nr1,\r\n");
  });

  it("quotes a value with a comma, a quote or a newline", () => {
    const csv = runTableToCsv(["run_name"], [row({ run_name: 'a,"b"\nc' })]);
    expect(csv).toBe('run_name\r\n"a,""b""\nc"\r\n');
  });
});

describe("rowToRun", () => {
  it("keeps the hyperparameters and final metrics the compare dialog reads", () => {
    const run = rowToRun(row({ param_n_estimators: null }));
    expect(run.parameters).toEqual({ max_depth: 6 });
    expect(run.metrics.val_auc).toEqual([{ key: "val_auc", value: 0.91 }]);
    expect(run.name).toBe("churn-1");
    expect(run.status).toBe("COMPLETED");
  });
});
