import { useCallback, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { Button } from "~/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "~/components/ui/card";
import { Label } from "~/components/ui/label";
import { Separator } from "~/components/ui/separator";

import { API_BASE_URL } from "../config";
import type { Route } from "./+types/_app.e2b-test";

const DEFAULT_CODE = `def run(params, ctx):
    ctx.log("starting run")
    value = params.get("value", 2)
    ctx.log(f"value from params: {value}")
    result = {
        "doubled": value * 2,
        "inputs_keys": list(ctx.read_inputs().keys()),
    }
    ctx.log("writing result artifact")
    ctx.write_outputs(result=result)
    ctx.log("Issuing ping RPC")
    rpc_response = ctx.rpc_call("ping", {"value": value})
    ctx.log(f"RPC response: {rpc_response}")
    return result
`;

const DEFAULT_PARAMS = `{
  "value": 3
}`;

type SandboxRunResult = {
  ok: boolean;
  sandboxId: string;
  logs: string[];
  files: {
    path: string;
    sizeBytes: number;
    preview: string | null;
  }[];
  error: string | null;
};

type SandboxApiResponse = {
  ok: boolean;
  sandbox_id: string;
  logs: string[];
  files: {
    path: string;
    size_bytes: number;
    preview: string | null;
  }[];
  error?: string | null;
};

export function meta({}: Route.MetaArgs) {
  return [
    { title: "E2B Sandbox | XLS Workspace" },
    {
      name: "description",
      content: "Run AI-authored Python snippets inside an E2B sandbox and inspect artifacts.",
    },
  ];
}

export default function E2BTestRoute() {
  const [code, setCode] = useState(DEFAULT_CODE);
  const [paramsText, setParamsText] = useState(DEFAULT_PARAMS);
  const [allowInternet, setAllowInternet] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SandboxRunResult | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const isBusy = isRunning;

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (isBusy) {
        return;
      }

      setError(null);
      setIsRunning(true);
      setResult(null);
      setLogs([]);

      try {
        const trimmed = paramsText.trim();
        const parsedParams = trimmed ? JSON.parse(trimmed) : {};

        const response = await fetch(`${API_BASE_URL}/api/e2b-test/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code,
            allow_internet: allowInternet,
            params: parsedParams,
          }),
        });

        if (!response.ok) {
          const contentType = response.headers.get("content-type") ?? "";
          if (contentType.includes("application/json")) {
            const problem = (await response.json()) as { detail?: unknown };
            const detail =
              typeof problem?.detail === "string"
                ? problem.detail
                : JSON.stringify(problem ?? {});
            throw new Error(detail || `Sandbox request failed (${response.status})`);
          }

          const message = await response.text();
          throw new Error(message || `Sandbox request failed (${response.status})`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("Streaming not supported by this browser.");
        }

        const decoder = new TextDecoder();
        let buffer = "";

        const processLine = (line: string) => {
          const trimmedLine = line.trim();
          if (!trimmedLine) {
            return;
          }

          const event = JSON.parse(trimmedLine) as {
            type: "log" | "result" | "error";
            lines?: string[];
            data?: SandboxApiResponse;
            detail?: unknown;
            message?: string;
          };

          if (event.type === "log" && Array.isArray(event.lines)) {
            setLogs((prev) => [...prev, ...event.lines!]);
            return;
          }

          if (event.type === "result" && event.data) {
            const payload = event.data;
            const normalized: SandboxRunResult = {
              ok: payload.ok ?? true,
              sandboxId: payload.sandbox_id,
              logs: payload.logs ?? [],
              files:
                payload.files?.map((file) => ({
                  path: file.path,
                  sizeBytes: file.size_bytes,
                  preview: file.preview ?? null,
                })) ?? [],
              error:
                typeof payload.error === "string" && payload.error.length > 0
                  ? payload.error
                  : null,
            };
            setResult(normalized);
            setLogs(normalized.logs);
            setIsRunning(false);
            return;
          }

          if (event.type === "error") {
            const detailText =
              typeof event.detail === "string"
                ? event.detail
                : event.message || "Sandbox run failed.";
            setError(detailText);
            setIsRunning(false);
          }
        };

        while (true) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          let newlineIndex: number;
          while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
            const line = buffer.slice(0, newlineIndex);
            buffer = buffer.slice(newlineIndex + 1);
            processLine(line);
          }
        }

        const leftover = buffer + decoder.decode();
        if (leftover.trim().length > 0) {
          processLine(leftover);
        }
      } catch (submissionError) {
        if (submissionError instanceof SyntaxError) {
          setError("Params must be valid JSON.");
        } else {
          setError(
            submissionError instanceof Error
              ? submissionError.message
              : "Unable to run code in the sandbox."
          );
        }
        setResult(null);
      } finally {
        setIsRunning(false);
      }
    },
    [allowInternet, code, isBusy, paramsText]
  );

  const artifactGroups = useMemo(() => {
    if (!result?.files?.length) {
      return [] as SandboxRunResult["files"];
    }
    return result.files;
  }, [result]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>E2B Sandbox Runner</CardTitle>
          <CardDescription>
            Provide a Python snippet that exposes <code>run(params, ctx)</code>. The API spins up a
            fresh sandbox, seeds the helper SDK, and returns execution logs plus generated files.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-6">
            <div className="grid gap-2">
              <Label htmlFor="code">Python code</Label>
              <textarea
                id="code"
                className="font-mono text-sm min-h-[220px] rounded-md border border-border bg-background px-3 py-2 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                spellCheck={false}
              />
              <p className="text-xs text-muted-foreground">
                The snippet must define <code>run(params, ctx)</code>. Use <code>ctx.log</code>,
                <code>ctx.write_outputs</code>, and <code>ctx.rpc_call</code> to interact with the host.
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="params">Params JSON</Label>
              <textarea
                id="params"
                className="font-mono text-xs min-h-[90px] rounded-md border border-border bg-background px-3 py-2 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={paramsText}
                onChange={(event) => setParamsText(event.target.value)}
                spellCheck={false}
              />
            </div>

            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={allowInternet}
                  onChange={(event) => setAllowInternet(event.target.checked)}
                />
                Allow internet access inside sandbox
              </label>
            </div>
          </CardContent>
          <CardFooter className="justify-between">
            <div className="flex flex-col text-xs text-muted-foreground">
              <span>Internet access is disabled by default for safety.</span>
              <span>Execution times out after 90 seconds.</span>
            </div>
            <Button type="submit" disabled={isBusy}>
              {isBusy ? "Running..." : "Run in sandbox"}
            </Button>
          </CardFooter>
        </form>
      </Card>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {(result || logs.length > 0 || error) && (
        <Card>
          <CardHeader className="flex flex-col gap-1">
            <CardTitle>Sandbox result</CardTitle>
            {result ? (
              <CardDescription>
                Sandbox ID: {result.sandboxId}
                {!result.ok && result.error ? ` — ${result.error}` : null}
              </CardDescription>
            ) : (
              <CardDescription>Streaming sandbox output…</CardDescription>
            )}
          </CardHeader>
          <CardContent className="space-y-6">
            {result && (
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Status:</span>
                <span className={result.ok ? "text-emerald-600" : "text-destructive"}>
                  {result.ok ? "Completed" : "Failed"}
                </span>
              </div>
            )}

            {result && !result.ok && result.error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                Sandbox process reported an error: {result.error}
              </div>
            )}

            <section className="space-y-3">
              <h3 className="text-sm font-semibold">Execution logs</h3>
              {logs.length === 0 ? (
                <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                  No log lines yet.
                </p>
              ) : (
                <pre className="max-h-[320px] overflow-y-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
                  {logs.join("\n")}
                </pre>
              )}
            </section>

            <Separator />

            <section className="space-y-3">
              <h3 className="text-sm font-semibold">Artifacts & Files</h3>
              {result ? (
                artifactGroups.length === 0 ? (
                  <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                    No files were produced during this run.
                  </p>
                ) : (
                  <ul className="space-y-3 text-xs">
                    {artifactGroups.map((file) => (
                      <li
                        key={file.path}
                        className="rounded-md border border-border bg-muted/30 p-3"
                      >
                        <div className="flex items-center justify-between gap-4 text-[11px] uppercase tracking-wide text-muted-foreground">
                          <span className="truncate font-medium normal-case text-foreground">
                            {file.path}
                          </span>
                          <span>{formatSize(file.sizeBytes)}</span>
                        </div>
                        {file.preview && (
                          <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded bg-background/80 p-2 text-[11px]">
                            {file.preview}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ul>
                )
              ) : (
                <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                  Waiting for sandbox completion before listing files.
                </p>
              )}
            </section>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function formatSize(sizeBytes: number) {
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }
  const kb = sizeBytes / 1024;
  if (kb < 1024) {
    return `${kb.toFixed(1)} KB`;
  }
  const mb = kb / 1024;
  return `${mb.toFixed(1)} MB`;
}
