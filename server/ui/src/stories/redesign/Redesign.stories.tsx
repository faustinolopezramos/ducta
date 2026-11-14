import type { Meta, StoryObj } from "@storybook/react";
import { Sparkline } from "../../components/ui/Sparkline";
import { KeyHint } from "../../components/ui/KeyHint";
import { EntityChip } from "../../components/ui/EntityChip";
import { RunOptionsDialog } from "../../components/Execution/RunOptionsDialog";
import { ExtractSubpipelineDialog } from "../../pages/PipelinePage/ExtractSubpipelineDialog";
import { ExtractTemplateDialog } from "../../pages/PipelinePage/ExtractTemplateDialog";
import { FailingRows } from "../../components/Quality/FailingRows";
import { CommentThreads } from "../../components/Comments/CommentThreads";
import { Shell } from "./decorators";

const meta = {
  title: "Redesign/Phase components",
  parameters: { layout: "padded" },
  tags: ["autodocs"],
} satisfies Meta;

export default meta;
type Story = StoryObj;

const runs = [4, 5, 4.6, 12, 5, 4.8, 5.1, 0.4, 5].map((seconds, i) => ({ seconds, status: i === 7 ? "failed" : "success" }));

export const RunTrend: Story = {
  render: () => <Sparkline points={runs} label="silver.clean: last 9 runs" width={160} height={24} />,
};

export const Shortcuts: Story = {
  render: () => (
    <p style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <KeyHint keys="mod+k" /> go to anything · <KeyHint keys="mod+shift+g" /> node ↔ code · <KeyHint keys="esc" /> close
    </p>
  ),
};

export const DatasetChip: Story = {
  render: () => (
    <Shell>
      <EntityChip
        kind="dataset"
        name="silver.education.student_cleaned"
        to="/p/demo/datasets/silver.education.student_cleaned"
        card={[["Format", "parquet"], ["Layer", "silver"], ["Owner", "data-education"], ["Written by", "silver.clean_student"]]}
      />
    </Shell>
  ),
};

export const RunWithOptions: Story = {
  render: () => (
    <RunOptionsDialog
      pipeline="silver.clean"
      env="dev"
      nodes={["silver.clean_student", "silver.clean_education"]}
      initialNode="silver.clean_student"
      onRun={() => {}}
      onCancel={() => {}}
    />
  ),
};

export const MakeTemplate: Story = {
  render: () => <ExtractTemplateDialog node="silver.clean_student" onExtract={() => {}} onCancel={() => {}} />,
};

export const MakeSubpipeline: Story = {
  render: () => (
    <ExtractSubpipelineDialog
      from="silver.clean_student"
      nodes={["silver.clean_student", "silver.clean_education", "golden.transformation_student"]}
      onExtract={() => {}}
      onCancel={() => {}}
    />
  ),
};

const failing = {
  check: "range",
  failing: 29,
  scanned: 395,
  columns: ["school", "sex", "age", "G3"],
  rows: [
    { school: "GP", sex: "M", age: 19, G3: 12 },
    { school: "GP", sex: "F", age: 20, G3: 9 },
    { school: "MS", sex: "M", age: 22, G3: null },
  ],
};
const failingArgs = { dataset: "silver.education.student_cleaned", env: "dev", check: "range", params: { column: "age", min: 15, max: 18 } };

export const RowsThatFailACheck: Story = {
  render: () => (
    <Shell data={[[["server-projects", "demo", "failing-rows", failingArgs], failing]]}>
      <FailingRows projectId="demo" {...failingArgs} />
    </Shell>
  ),
};

const threads = {
  threads: [
    {
      id: "a",
      anchor: { pipeline: "silver.clean", node: "silver.clean_student" },
      author: "Ana",
      body: "Why drop rows without an id here instead of quarantining them?",
      created_at: "2026-10-08T10:00:00Z",
      resolved: false,
      replies: [{ id: "r", author: "Luis", body: "Upstream sends empty ids on retries.", created_at: "2026-10-08T11:00:00Z" }],
    },
  ],
};

export const Comments: Story = {
  render: () => (
    <Shell data={[[["server-projects", "demo", "comments", { node: "silver.clean_student" }], threads]]}>
      <div style={{ width: 380 }}>
        <CommentThreads
          projectId="demo"
          filter={{ node: "silver.clean_student" }}
          anchor={{ pipeline: "silver.clean", node: "silver.clean_student" }}
          label="comments on silver.clean_student"
        />
      </div>
    </Shell>
  ),
};
