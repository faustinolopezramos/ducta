import * as yaml from "js-yaml";

export function loadYamlSafe(yamlText: string): unknown[] {
  try {
    const results: unknown[] = [];
    yaml.loadAll(yamlText, (doc: unknown) => {
      if (doc !== undefined && doc !== null) {
        results.push(doc);
      }
    });
    return results;
  } catch (error) {
    throw new Error(`YAML parse error: ${error instanceof Error ? error.message : "Unknown error"}`);
  }
}
