import { describe, expect, it } from "vitest";

async function readText(path: string): Promise<string> {
  const [{ readFile }, { join }] = await Promise.all([
    import("node:fs/promises"),
    import("node:path"),
  ]);
  return readFile(join(process.cwd(), path), "utf8");
}

describe("Netlify invocations edge function", () => {
  it("injects AgentArts gateway auth from server-side environment", async () => {
    const source = await readText("netlify/edge-functions/invocations.ts");

    expect(source).toContain('Netlify.env.get("AGENTARTS_API_KEY")');
    expect(source).toContain('Netlify.env.get("AGENTARTS_INVOCATIONS_URL")');
    expect(source).toContain('"Authorization"');
    expect(source).not.toContain("REPLACE_WITH_AGENTARTS_GATEWAY_API_KEY");
  });

  it("routes /invocations through the edge function", async () => {
    const config = await readText("netlify.toml");

    expect(config).toContain("[[edge_functions]]");
    expect(config).toContain('function = "invocations"');
    expect(config).toContain('path = "/invocations"');
  });
});
