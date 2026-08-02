export function basename(module = "") {
  return module.split(".").at(-1) || "module";
}
