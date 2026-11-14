import { describe, it, expect } from 'vitest';
import { buildStartCommand, shellQuote } from './cliCommand';

describe('shellQuote', () => {
  it('leaves safe values unquoted', () => {
    expect(shellQuote('dev')).toBe('dev');
    expect(shellQuote('my_pipeline-1')).toBe('my_pipeline-1');
    expect(shellQuote('2024-01-01')).toBe('2024-01-01');
  });

  it('quotes the empty string', () => {
    expect(shellQuote('')).toBe("''");
  });

  it('quotes values with spaces', () => {
    expect(shellQuote('my pipeline')).toBe("'my pipeline'");
  });

  it('escapes embedded single quotes', () => {
    expect(shellQuote("a'b")).toBe("'a'\\''b'");
  });
});

describe('buildStartCommand', () => {
  it('emits a minimal command with just the pipeline', () => {
    expect(buildStartCommand({ pipelineName: 'ingest' })).toBe(
      'ducta start --pipeline ingest'
    );
  });

  it('includes env, dates, node and flags when provided', () => {
    const cmd = buildStartCommand({
      pipelineName: 'ingest',
      env: 'prod',
      nodeName: 'load_raw',
      startDate: '2024-01-01',
      endDate: '2024-01-31',
      dryRun: true,
    });
    expect(cmd).toBe(
      'ducta start --pipeline ingest --env prod --node load_raw ' +
        '--start-date 2024-01-01 --end-date 2024-01-31 --dry-run'
    );
  });

  it('omits flags that are absent or false', () => {
    const cmd = buildStartCommand({
      pipelineName: 'ingest',
      env: 'dev',
      dryRun: false,
      validateOnly: false,
    });
    expect(cmd).toBe('ducta start --pipeline ingest --env dev');
  });

  it('emits --validate-only when set', () => {
    expect(
      buildStartCommand({ pipelineName: 'ingest', validateOnly: true })
    ).toBe('ducta start --pipeline ingest --validate-only');
  });

  it('quotes a pipeline name with spaces', () => {
    expect(buildStartCommand({ pipelineName: 'my pipeline' })).toBe(
      "ducta start --pipeline 'my pipeline'"
    );
  });
});
