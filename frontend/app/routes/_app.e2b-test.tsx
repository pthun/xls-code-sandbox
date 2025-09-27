import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Code,
  Download,
  Loader2,
  Play,
  Send,
  Trash2,
} from "lucide-react";

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
import { cn } from "~/lib/utils";

import { API_BASE_URL } from "../config";
import type { Route } from "./+types/_app.e2b-test";

const DEFAULT_CODE = `def run(params, ctx):
    """Example run implementation."""
    ctx.log("starting example run")
    value = params.get("value", 2)
    data = ctx.read_inputs()
    ctx.log(f"loaded input keys: {list(data.keys())}")
    result = {
        "doubled": value * 2,
        "input_keys": list(data.keys()),
    }
    ctx.write_outputs(result=result)
    return result
`;

const DEFAULT_PARAMS = `{
  "value": 3
}`;

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  code?: string | null;
  pipPackages?: string[];
  kind?: "run-result";
};

type ChatApiResponse = {
  message: { role: "assistant"; content: string };
  code: string | null;
  pip_packages: string[];
  usage?: {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
  } | null;
  raw?: string | null;
};

type SandboxRunResult = {
  runId: string;
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
  run_id?: string | null;
};

type RunSummary = {
  id: string;
  created_at: string;
  ok: boolean | null;
  error: string | null;
};

type RunFileRecord = {
  sandbox_path: string;
  local_path: string;
  size_bytes: number;
  download_url: string;
};

type RunDetail = RunSummary & {
  code: string;
  params: Record<string, unknown>;
  pip_packages: string[];
  allow_internet: boolean;
  logs: string[];
  files: RunFileRecord[];
};

export function meta({}: Route.MetaArgs) {
  return [
    { title: "E2B Assistant | XLS Workspace" },
    {
      name: "description",
      content: "Collaborate with ChatGPT to build sandbox code, then run it directly in E2B.",
    },
  ];
}

function createId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, exponent);
  const precision = value >= 10 || exponent === 0 ? 0 : 1;
  return `${value.toFixed(precision)} ${units[exponent]}`;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function buildRunResultMessage(result: SandboxRunResult, logLines: string[]): string {
  const lines: string[] = ["<RunResult>", `status: ${result.ok ? "success" : "failure"}`];
  if (result.runId) {
    lines.push(`run_id: ${result.runId}`);
  }
  if (result.error) {
    lines.push(`error: ${result.error}`);
  }
  lines.push("logs:");
  if (logLines.length) {
    lines.push(...logLines);
  } else {
    lines.push("<none>");
  }
  lines.push("artifacts:");
  if (result.files.length) {
    lines.push(
      ...result.files.map((file) => `${file.path} (${formatBytes(file.sizeBytes)})`)
    );
  } else {
    lines.push("<none>");
  }
  lines.push("</RunResult>");
  return lines.join("\n");
}

function stripRunResultTags(content: string) {
  return content.replace(/<\/??RunResult>/gi, "").trim();
}

export default function E2BAssistantRoute() {
  const [messages, setMessages] = useState<ChatMessage[]>(() => [
    {
      id: createId(),
      role: "assistant",
      content:
        "Hi! Describe the tool you’d like to build. I’ll suggest Python code for the sandbox and list any pip packages I need.",
    },
  ]);
  const [input, setInput] = useState("");
  const [currentCode, setCurrentCode] = useState<string>(DEFAULT_CODE);
  const [pipPackages, setPipPackages] = useState<string[]>([]);
  const [paramsText, setParamsText] = useState<string>(DEFAULT_PARAMS);

  const [chatError, setChatError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<SandboxRunResult | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [runHistory, setRunHistory] = useState<RunSummary[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [isRunDetailLoading, setIsRunDetailLoading] = useState(false);
  const [runDetailError, setRunDetailError] = useState<string | null>(null);

  const [showCode, setShowCode] = useState(false);
  const [showPip, setShowPip] = useState(false);

  const fetchRunHistory = useCallback(async () => {
    try {
      setIsHistoryLoading(true);
      setHistoryError(null);
      const response = await fetch(`${API_BASE_URL}/api/e2b-runs`);
      if (!response.ok) {
        throw new Error(`Failed to load run history (${response.status})`);
      }
      const data = (await response.json()) as RunSummary[];
      setRunHistory(data);
      return data;
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "Unable to load run history"
      );
      return [] as RunSummary[];
    } finally {
      setIsHistoryLoading(false);
    }
  }, []);

  const fetchRunDetail = useCallback(async (runId: string) => {
    try {
      setIsRunDetailLoading(true);
      setRunDetailError(null);
      const response = await fetch(`${API_BASE_URL}/api/e2b-runs/${runId}`);
      if (!response.ok) {
        throw new Error(`Failed to load run detail (${response.status})`);
      }
      const data = (await response.json()) as RunDetail;
      setRunDetail(data);
    } catch (error) {
      setRunDetailError(
        error instanceof Error ? error.message : "Unable to load run detail"
      );
      setRunDetail(null);
    } finally {
      setIsRunDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchRunHistory();
  }, [fetchRunHistory]);

  const handleSend = useCallback(
    async (event?: FormEvent<HTMLFormElement>) => {
      if (event) event.preventDefault();
      const content = input.trim();
      if (!content || isGenerating) {
        return;
      }

      const newUserMessage: ChatMessage = {
        id: createId(),
        role: "user",
        content,
      };

      setMessages((prev) => [...prev, newUserMessage]);
      setInput("");
      setChatError(null);
      setIsGenerating(true);

      try {
        const history = messages
          .map((message) => ({ role: message.role, content: message.content }))
          .filter((message) => message.content.trim().length > 0);

        if (currentCode.trim().length > 0) {
          history.push({
            role: "user",
            content: `Current code:\n<CodeOutput>${currentCode}</CodeOutput>`,
          });
        }

        if (pipPackages.length > 0) {
          history.push({
            role: "user",
            content: `Current pip requirements:\n<Pip>\n${pipPackages.join("\n")}\n</Pip>`,
          });
        }

        history.push({ role: "user", content });

        const response = await fetch(`${API_BASE_URL}/api/e2b-chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: history }),
        });

        if (!response.ok) {
          const detail = await response.text();
          throw new Error(detail || "Chat request failed");
        }

        const payload = (await response.json()) as ChatApiResponse;
        const assistantMessage: ChatMessage = {
          id: createId(),
          role: "assistant",
          content: payload.message.content.trim(),
          code: payload.code,
          pipPackages: payload.pip_packages,
        };

        setMessages((prev) => [...prev, assistantMessage]);

        if (typeof payload.code === "string" && payload.code.trim().length > 0) {
          setCurrentCode(payload.code.trim());
        }

        if (Array.isArray(payload.pip_packages)) {
          setPipPackages(payload.pip_packages);
        }
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to contact the assistant";
        setChatError(message);
      } finally {
        setIsGenerating(false);
      }
    },
    [input, isGenerating, messages, currentCode, pipPackages]
  );

  const handleRun = useCallback(async () => {
    if (isRunning) {
      return;
    }

    if (!currentCode.trim()) {
      setRunError("No code has been generated yet.");
      return;
    }

    let parsedParams: unknown;
    try {
      parsedParams = paramsText.trim() ? JSON.parse(paramsText) : {};
    } catch (error) {
      setRunError("Parameters JSON is invalid. Fix it before running.");
      return;
    }

    setIsRunning(true);
    setRunError(null);
    setResult(null);
    setLogs([]);

    try {
      const liveLogs: string[] = [];

      const response = await fetch(`${API_BASE_URL}/api/e2b-test/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: currentCode,
          allow_internet: pipPackages.length > 0,
          params: parsedParams,
          pip_packages: pipPackages,
        }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "Sandbox request failed");
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Streaming not supported by this browser");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      const processLine = (line: string) => {
        const trimmedLine = line.trim();
        if (!trimmedLine) return;
        const event = JSON.parse(trimmedLine) as {
          type: "log" | "result" | "error";
          lines?: string[];
          data?: SandboxApiResponse;
          detail?: unknown;
          message?: string;
        };

        if (event.type === "log" && Array.isArray(event.lines)) {
          liveLogs.push(...event.lines);
          setLogs((prev) => [...prev, ...event.lines!]);
          return;
        }

        if (event.type === "result" && event.data) {
          const payload = event.data;
          const normalized: SandboxRunResult = {
            runId: payload.run_id ?? "",
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
          setLogs(normalized.logs.length ? normalized.logs : liveLogs);
          setResult(normalized);
          const combinedLogs = normalized.logs.length ? normalized.logs : liveLogs;
          const recentLogs = combinedLogs.slice(-40);
          const runMessage: ChatMessage = {
            id: createId(),
            role: "user",
            content: buildRunResultMessage(normalized, recentLogs),
            kind: "run-result",
          };
          setMessages((prev) => [...prev, runMessage]);
          setSelectedRunId(normalized.runId || null);
          void fetchRunHistory().then((history) => {
            if (normalized.runId) {
              const exists = history.some((item) => item.id === normalized.runId);
              if (exists) {
                void fetchRunDetail(normalized.runId);
              }
            }
          });
          return;
        }

        if (event.type === "error") {
          const detailText =
            typeof event.detail === "string"
              ? event.detail
              : event.message || "Sandbox run failed.";
          setRunError(detailText);
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
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
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to execute code in the sandbox";
      setRunError(message);
    } finally {
      setIsRunning(false);
      void fetchRunHistory();
    }
  }, [
    currentCode,
    pipPackages,
    paramsText,
    isRunning,
    fetchRunHistory,
    fetchRunDetail,
  ]);

  const handleSelectRun = useCallback(
    async (runId: string) => {
      setSelectedRunId(runId);
      await fetchRunDetail(runId);
    },
    [fetchRunDetail]
  );

  const handleDeleteRun = useCallback(
    async (runId: string) => {
      const confirmed = window.confirm("Delete this run and all associated files?");
      if (!confirmed) {
        return;
      }
      try {
        const response = await fetch(`${API_BASE_URL}/api/e2b-runs/${runId}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          throw new Error(`Failed to delete run (${response.status})`);
        }
        if (selectedRunId === runId) {
          setSelectedRunId(null);
          setRunDetail(null);
        }
        await fetchRunHistory();
      } catch (error) {
        setHistoryError(
          error instanceof Error ? error.message : "Unable to delete run"
        );
      }
    },
    [fetchRunHistory, selectedRunId]
  );

  const artifacts = useMemo(() => result?.files ?? [], [result]);

  return (
    <div className="mx-auto flex w-full flex-col gap-6 lg:flex-row">
      <div className="flex-1 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Chat with the Assistant</CardTitle>
            <CardDescription>
              Iterate on the sandbox script through conversation. The assistant updates the code and
              pip requirements using structured tags.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-col gap-3">
              {messages.map((message) => {
                const isAssistant = message.role === "assistant";
                const baseStyles = cn(
                  "max-w-full rounded-md border px-3 py-2 text-sm whitespace-pre-wrap",
                  isAssistant ? "self-start bg-muted" : "self-end bg-primary/10"
                );

                if (message.kind === "run-result") {
                  return (
                    <div key={message.id} className={baseStyles}>
                      <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
                        Run results shared
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {stripRunResultTags(message.content) || "Latest sandbox output."}
                      </p>
                    </div>
                  );
                }

                return (
                  <div key={message.id} className={baseStyles}>
                    <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
                      {isAssistant ? "Assistant" : "You"}
                    </div>
                    <div>{message.content}</div>
                    {isAssistant && message.code && (
                      <p className="mt-2 text-xs text-muted-foreground">Updating code…</p>
                    )}
                    {isAssistant && message.pipPackages && message.pipPackages.length > 0 && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Pip requirements updated ({message.pipPackages.length}).
                      </p>
                    )}
                  </div>
                );
              })}
              {isGenerating && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Thinking…
                </div>
              )}
            </div>
            {chatError && (
              <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {chatError}
              </p>
            )}
          </CardContent>
          <CardFooter>
            <form onSubmit={handleSend} className="flex w-full flex-col gap-3">
              <textarea
                className="min-h-[120px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="Explain what you’d like to build or ask the assistant to modify the code."
                value={input}
                onChange={(event) => setInput(event.target.value)}
                disabled={isGenerating}
              />
              <div className="flex items-center justify-end gap-2">
                <Button type="submit" disabled={isGenerating || !input.trim()}>
                  {isGenerating ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" /> Generating…
                    </>
                  ) : (
                    <>
                      <Send className="mr-2 size-4" /> Send
                    </>
                  )}
                </Button>
              </div>
            </form>
          </CardFooter>
        </Card>

        {(isRunning || runError || result || logs.length > 0) && (
          <Card>
            <CardHeader>
              <CardTitle>Sandbox Run</CardTitle>
              <CardDescription>
                Execute the latest code and review logs and artifacts. Runs automatically share a
                summary back with the assistant.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {isRunning && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Running in the sandbox…
                </div>
              )}

              {runError && (
                <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {runError}
                </p>
              )}

              {result && (
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span>Status</span>
                    <span className={result.ok ? "text-emerald-600" : "text-destructive"}>
                      {result.ok ? "Completed" : "Failed"}
                    </span>
                  </div>
                  {result.runId && (
                    <p className="text-xs text-muted-foreground">Run ID: {result.runId}</p>
                  )}
                  {result.error && (
                    <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                      {result.error}
                    </p>
                  )}
                </div>
              )}

              <section className="space-y-2">
                <h3 className="text-sm font-semibold">Logs</h3>
                {logs.length === 0 ? (
                  <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                    No log output yet.
                  </p>
                ) : (
                  <pre className="max-h-[320px] overflow-y-auto rounded-md border border-border bg-muted/30 p-3 text-xs">
                    {logs.join("\n")}
                  </pre>
                )}
              </section>

              <Separator />

              <section className="space-y-2">
                <h3 className="text-sm font-semibold">Artifacts</h3>
                {artifacts.length === 0 ? (
                  <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                    No artifacts were produced during this run.
                  </p>
                ) : (
                  <ul className="space-y-3 text-xs">
                    {artifacts.map((file) => (
                      <li key={file.path} className="rounded-md border border-border bg-muted/30 p-3">
                        <div className="flex items-center justify-between gap-4 text-[11px] uppercase tracking-wide text-muted-foreground">
                          <span className="truncate font-medium normal-case text-foreground">
                            {file.path}
                          </span>
                          <span>{formatBytes(file.sizeBytes)}</span>
                        </div>
                        {file.preview && (
                          <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded bg-background/80 p-2 text-[11px]">
                            {file.preview}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Run history</CardTitle>
            <CardDescription>
              Review previous sandbox executions. Select a run to inspect or remove it.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {historyError && (
              <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {historyError}
              </p>
            )}
            {isHistoryLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Loading runs…
              </div>
            ) : runHistory.length === 0 ? (
              <p className="text-sm text-muted-foreground">No sandbox runs recorded yet.</p>
            ) : (
              <ul className="space-y-2">
                {runHistory.map((run) => {
                  const isSelected = selectedRunId === run.id;
                  return (
                    <li
                      key={run.id}
                      className={cn(
                        "rounded-md border border-border px-3 py-2 text-sm transition",
                        isSelected ? "bg-accent/30" : "bg-background"
                      )}
                    >
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{formatDateTime(run.created_at)}</span>
                          <div className="flex items-center gap-1">
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              onClick={() => handleSelectRun(run.id)}
                            >
                              View
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              onClick={() => handleDeleteRun(run.id)}
                            >
                              <Trash2 className="mr-1 size-3" /> Delete
                            </Button>
                          </div>
                        </div>
                        <div className="flex items-center justify-between text-xs text-muted-foreground">
                          <span>
                            Status: {run.ok == null ? "unknown" : run.ok ? "success" : "failure"}
                          </span>
                          {run.error && <span className="text-destructive">{run.error}</span>}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        {selectedRunId && (
          <Card>
            <CardHeader>
              <CardTitle>Run details</CardTitle>
              <CardDescription>{selectedRunId}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {isRunDetailLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Loading run details…
                </div>
              ) : runDetailError ? (
                <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {runDetailError}
                </p>
              ) : runDetail ? (
                <div className="space-y-4 text-sm">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{formatDateTime(runDetail.created_at)}</span>
                    <span
                      className={
                        runDetail.ok == null
                          ? "text-muted-foreground"
                          : runDetail.ok
                          ? "text-emerald-600"
                          : "text-destructive"
                      }
                    >
                      {runDetail.ok == null ? "Unknown" : runDetail.ok ? "Success" : "Failure"}
                    </span>
                  </div>
                  {runDetail.error && (
                    <p className="text-xs text-destructive">{runDetail.error}</p>
                  )}

                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Code snapshot</h3>
                    <pre className="max-h-[320px] overflow-y-auto rounded-md border border-border bg-muted/20 p-3 text-xs">
                      {runDetail.code}
                    </pre>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Parameters</h3>
                    <pre className="rounded-md border border-border bg-muted/20 p-3 text-xs">
                      {JSON.stringify(runDetail.params, null, 2)}
                    </pre>
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Pip packages</h3>
                    {runDetail.pip_packages.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No packages were installed.</p>
                    ) : (
                      <ul className="space-y-1 text-xs">
                        {runDetail.pip_packages.map((pkg) => (
                          <li key={pkg} className="rounded bg-muted/30 px-2 py-1 font-mono">
                            {pkg}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Logs</h3>
                    {runDetail.logs.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No logs were captured.</p>
                    ) : (
                      <pre className="max-h-[240px] overflow-y-auto rounded-md border border-border bg-muted/20 p-3 text-xs">
                        {runDetail.logs.join("\n")}
                      </pre>
                    )}
                  </section>

                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Files</h3>
                    {runDetail.files.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No files were preserved.</p>
                    ) : (
                      <ul className="space-y-2 text-xs">
                        {runDetail.files.map((file) => (
                          <li
                            key={file.local_path}
                            className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2"
                          >
                            <div className="flex-1">
                              <p className="font-mono">{file.sandbox_path}</p>
                              <p className="text-[11px] text-muted-foreground">
                                {file.local_path} · {formatBytes(file.size_bytes)}
                              </p>
                            </div>
                            <Button asChild variant="ghost" size="icon" title="Download file">
                              <a
                                href={`${API_BASE_URL}${file.download_url}`}
                                target="_blank"
                                rel="noreferrer"
                              >
                                <Download className="size-4" />
                              </a>
                            </Button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Select a run to view details.</p>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      <aside className="w-full space-y-4 lg:w-80 lg:shrink-0">
        <Card>
          <CardHeader className="flex items-center justify-between gap-2">
            <div>
              <CardTitle>Latest code</CardTitle>
              <CardDescription>View or copy the module sent to the sandbox.</CardDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setShowCode((prev) => !prev)}
            >
              <Code className="size-4" />
            </Button>
          </CardHeader>
          {showCode && (
            <CardContent>
              <pre className="max-h-[480px] overflow-y-auto rounded-md border border-border bg-muted/30 p-3 text-xs">
                {currentCode.trim() || "No code generated yet."}
              </pre>
            </CardContent>
          )}
        </Card>

        <Card>
          <CardHeader className="flex items-center justify-between gap-2">
            <div>
              <CardTitle>Pip requirements</CardTitle>
              <CardDescription>Packages installed before each run.</CardDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setShowPip((prev) => !prev)}
            >
              {showPip ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            </Button>
          </CardHeader>
          {showPip && (
            <CardContent>
              {pipPackages.length === 0 ? (
                <p className="text-xs text-muted-foreground">No external packages required.</p>
              ) : (
                <ul className="space-y-1 text-xs">
                  {pipPackages.map((pkg) => (
                    <li key={pkg} className="rounded bg-muted/40 px-2 py-1 font-mono">
                      {pkg}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          )}
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Run configuration</CardTitle>
            <CardDescription>Adjust parameters and execute the sandbox.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="run-params">Params JSON</Label>
              <textarea
                id="run-params"
                className="min-h-[120px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={paramsText}
                onChange={(event) => setParamsText(event.target.value)}
                spellCheck={false}
              />
            </div>
          </CardContent>
          <CardFooter>
            <Button type="button" disabled={isRunning} onClick={handleRun} className="w-full">
              {isRunning ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" /> Running…
                </>
              ) : (
                <>
                  <Play className="mr-2 size-4" /> Run in sandbox
                </>
              )}
            </Button>
          </CardFooter>
        </Card>
      </aside>
    </div>
  );
}
