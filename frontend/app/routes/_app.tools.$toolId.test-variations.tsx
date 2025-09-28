import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link, useOutletContext } from "react-router";
import {
  Download,
  Loader2,
  Play,
  RefreshCcw,
} from "lucide-react";

import { Button } from "~/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "~/components/ui/card";
import { Label } from "~/components/ui/label";
import { cn } from "~/lib/utils";

import { API_BASE_URL } from "../config";
import type { ToolLayoutContextValue } from "./_app.tools";

type VariationFile = {
  filename: string;
  path: string;
  size_bytes: number;
  modified_at: string;
};


type Variation = {
  id: string;
  tool_id: number;
  label: string | null;
  created_at: string;
  prefix: string;
  files: VariationFile[];
};

type ParamSpec = {
  name: string;
  type?: string | null;
  required: boolean;
  description?: string | null;
};

type FileRequirement = {
  pattern: string;
  required: boolean;
  description?: string | null;
};

type RunSummary = {
  id: string;
  created_at: string;
  ok: boolean | null;
  error: string | null;
  code_version: number;
  folder_prefix?: string | null;
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

type SandboxRunResult = {
  runId: string;
  codeVersion: number | null;
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
  code_version?: number | null;
};

type PendingRun = {
  tempId: string;
  created_at: string;
  logs: string[];
  files: {
    path: string;
    sizeBytes: number;
    preview: string | null;
  }[];
  ok: boolean | null;
  error: string | null;
  status: "running" | "completed" | "failed";
  runId?: string;
  codeVersion: number | null;
};

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

function formatRunError(detail: unknown, fallback = "Sandbox run failed.") {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (typeof detail !== "object") return fallback;
  const record = detail as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof record.message === "string" && record.message.trim().length > 0) {
    parts.push(record.message.trim());
  }
  const missingParams = Array.isArray(record.missing_params)
    ? (record.missing_params as unknown[]).filter((item): item is string => typeof item === "string")
    : [];
  if (missingParams.length) {
    parts.push(`Missing params: ${missingParams.join(", ")}.`);
  }
  const invalidParams = Array.isArray(record.invalid_params)
    ? (record.invalid_params as unknown[]).filter(
        (item): item is { name?: string; expected?: string } =>
          !!item && typeof item === "object" && "name" in item
      )
    : [];
  if (invalidParams.length) {
    const formatted = invalidParams
      .map((item) => {
        const name = typeof (item as Record<string, unknown>).name === "string"
          ? (item as Record<string, unknown>).name
          : "unknown";
        const expected = typeof (item as Record<string, unknown>).expected === "string"
          ? (item as Record<string, unknown>).expected
          : "";
        const actual = typeof (item as Record<string, unknown>).actual === "string"
          ? (item as Record<string, unknown>).actual
          : "";
        if (expected && actual) {
          return `${name} (expected ${expected}, got ${actual})`;
        }
        return expected ? `${name} (expected ${expected})` : name;
      })
      .join(", ");
    parts.push(`Param type mismatch: ${formatted}.`);
  }
  const missingFiles = Array.isArray(record.missing_files)
    ? (record.missing_files as unknown[]).filter((item): item is string => typeof item === "string")
    : [];
  if (missingFiles.length) {
    parts.push(`Missing files: ${missingFiles.join(", ")}.`);
  }
  if (parts.length === 0) {
    return fallback;
  }
  return parts.join(" ");
}

function buildDefaultParams(specs: ParamSpec[]): string {
  if (!specs.length) return "{}";
  const template: Record<string, unknown> = {};
  for (const spec of specs) {
    if (!spec.name) continue;
    const type = (spec.type || "string").toLowerCase();
    if (type === "integer" || type === "int" || type === "number" || type === "float") {
      template[spec.name] = 0;
    } else if (type === "boolean" || type === "bool") {
      template[spec.name] = false;
    } else if (type === "array" || type === "list") {
      template[spec.name] = [];
    } else if (type === "object" || type === "dict") {
      template[spec.name] = {};
    } else {
      template[spec.name] = "";
    }
  }
  return JSON.stringify(template, null, 2);
}

function variationTitle(variation: Variation): string {
  if (variation.label && variation.label.trim().length > 0) {
    return variation.label.trim();
  }
  return `Variation ${variation.id}`;
}

export default function TestVariationsView() {
  const { tool } = useOutletContext<ToolLayoutContextValue>();
  const toolApiBase = useMemo(() => `${API_BASE_URL}/api/tools/${tool.id}`, [tool.id]);

  const [variations, setVariations] = useState<Variation[]>([]);
  const [isLoadingVariations, setIsLoadingVariations] = useState(false);
  const [variationsError, setVariationsError] = useState<string | null>(null);
  const [selectedVariationId, setSelectedVariationId] = useState<string | null>(null);

  const selectedVariation = useMemo(
    () => variations.find((variation) => variation.id === selectedVariationId) ?? null,
    [variations, selectedVariationId]
  );

  const [currentCode, setCurrentCode] = useState<string>("");
  const [pipPackages, setPipPackages] = useState<string[]>([]);
  const [currentVersion, setCurrentVersion] = useState<number | null>(null);
  const [paramSpecs, setParamSpecs] = useState<ParamSpec[]>([]);
  const [requiredFiles, setRequiredFiles] = useState<FileRequirement[]>([]);
  const [paramsText, setParamsText] = useState<string>("{}");
  const [isCodeLoading, setIsCodeLoading] = useState(false);
  const [codeError, setCodeError] = useState<string | null>(null);

  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [pendingRun, setPendingRun] = useState<PendingRun | null>(null);
  const [runHistory, setRunHistory] = useState<RunSummary[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [isRunDetailLoading, setIsRunDetailLoading] = useState(false);
  const [runDetailError, setRunDetailError] = useState<string | null>(null);

  const loadVariations = useCallback(async () => {
    setIsLoadingVariations(true);
    setVariationsError(null);
    try {
      const response = await fetch(`${toolApiBase}/variations`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Failed to load variations (${response.status})`);
      }
      const data = (await response.json()) as Variation[];
      setVariations(data);
      if (data.length > 0) {
        setSelectedVariationId((current) => current ?? data[0].id);
      } else {
        setSelectedVariationId(null);
      }
    } catch (error) {
      setVariationsError(
        error instanceof Error ? error.message : "Unable to load variations"
      );
    } finally {
      setIsLoadingVariations(false);
    }
  }, [toolApiBase]);

  useEffect(() => {
    void loadVariations();
  }, [loadVariations]);

  useEffect(() => {
    if (variations.length === 0) {
      setSelectedVariationId(null);
      return;
    }
    if (!selectedVariationId) {
      setSelectedVariationId(variations[0].id);
      return;
    }
    const exists = variations.some((variation) => variation.id === selectedVariationId);
    if (!exists) {
      setSelectedVariationId(variations[0].id);
    }
  }, [variations, selectedVariationId]);

  const fetchCurrentCodeVersion = useCallback(async () => {
    setIsCodeLoading(true);
    setCodeError(null);
    try {
      const response = await fetch(`${toolApiBase}/e2b-code/current`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Failed to load current code (${response.status})`);
      }
      const detail = await response.json() as {
        version: number;
        code: string;
        pip_packages: string[];
        params: ParamSpec[];
        required_files: FileRequirement[];
      };
      setCurrentCode(detail.code);
      setCurrentVersion(detail.version);
      setPipPackages(Array.isArray(detail.pip_packages) ? detail.pip_packages : []);
      setParamSpecs(Array.isArray(detail.params) ? detail.params : []);
      setRequiredFiles(Array.isArray(detail.required_files) ? detail.required_files : []);
      setParamsText((prev) => (prev === "{}" || prev.trim().length === 0 ? buildDefaultParams(detail.params ?? []) : prev));
    } catch (error) {
      setCodeError(error instanceof Error ? error.message : "Unable to load code version");
    } finally {
      setIsCodeLoading(false);
    }
  }, [toolApiBase]);

  useEffect(() => {
    void fetchCurrentCodeVersion();
  }, [fetchCurrentCodeVersion]);

  const fetchRunHistory = useCallback(
    async (folderPrefix: string) => {
      setIsHistoryLoading(true);
      setHistoryError(null);
      try {
        const response = await fetch(
          `${toolApiBase}/e2b-runs?folder_prefix=${encodeURIComponent(folderPrefix)}`,
          { headers: { Accept: "application/json" } }
        );
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
        setRunHistory([]);
        return [] as RunSummary[];
      } finally {
        setIsHistoryLoading(false);
      }
    },
    [toolApiBase]
  );

  const fetchRunDetail = useCallback(
    async (runId: string) => {
      setIsRunDetailLoading(true);
      setRunDetailError(null);
      try {
        const response = await fetch(`${toolApiBase}/e2b-runs/${runId}`, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error(`Failed to load run detail (${response.status})`);
        }
        const data = (await response.json()) as RunDetail;
        setRunDetail(data);
        return data;
      } catch (error) {
        setRunDetailError(
          error instanceof Error ? error.message : "Unable to load run detail"
        );
        setRunDetail(null);
        return null;
      } finally {
        setIsRunDetailLoading(false);
      }
    },
    [toolApiBase]
  );

  useEffect(() => {
    setRunHistory([]);
    setPendingRun(null);
    setSelectedRunId(null);
    setRunDetail(null);
    setRunDetailError(null);
    if (!selectedVariation) {
      return;
    }
    void fetchRunHistory(selectedVariation.prefix);
  }, [fetchRunHistory, selectedVariation]);

  const combinedRunHistory = useMemo(() => {
    if (!pendingRun) {
      return runHistory;
    }
    const placeholder: RunSummary = {
      id: pendingRun.tempId,
      created_at: pendingRun.created_at,
      ok: pendingRun.ok,
      error: pendingRun.error,
      code_version: pendingRun.codeVersion ?? currentVersion ?? 0,
      folder_prefix: selectedVariation?.prefix,
    };
    return [placeholder, ...runHistory];
  }, [pendingRun, runHistory, currentVersion, selectedVariation?.prefix]);

  const selectedRunIsPending = useMemo(() => {
    return pendingRun != null && selectedRunId === pendingRun.tempId;
  }, [pendingRun, selectedRunId]);

  const handleRun = useCallback(async () => {
    if (!selectedVariation || isRunning) {
      return;
    }

    if (!currentCode.trim()) {
      setRunError("Current code is empty. Generate or load code before running.");
      return;
    }

    let parsedParams: unknown;
    try {
      parsedParams = paramsText.trim() ? JSON.parse(paramsText) : {};
    } catch (error) {
      setRunError("Parameters JSON is invalid. Fix it before running.");
      return;
    }

    const tempId = createId();
    setPendingRun({
      tempId,
      created_at: new Date().toISOString(),
      logs: [],
      files: [],
      ok: null,
      error: null,
      status: "running",
      runId: undefined,
      codeVersion: currentVersion,
    });
    setSelectedRunId(tempId);
    setRunDetail(null);
    setRunDetailError(null);
    setIsRunning(true);
    setRunError(null);

    try {
      const liveLogs: string[] = [];
      const response = await fetch(`${toolApiBase}/e2b-test/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: currentCode,
          allow_internet: pipPackages.length > 0,
          params: parsedParams,
          pip_packages: pipPackages,
          code_version: currentVersion,
          folder_prefix: selectedVariation.prefix,
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

      const appendLogs = (lines: string[]) => {
        if (!lines.length) return;
        setPendingRun((prev) =>
          prev ? { ...prev, logs: [...prev.logs, ...lines] } : prev
        );
      };

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
          appendLogs(event.lines);
          return;
        }

        if (event.type === "result" && event.data) {
          const payload = event.data;
          const normalized: SandboxRunResult = {
            runId: payload.run_id ?? "",
            codeVersion: typeof payload.code_version === "number" ? payload.code_version : null,
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
          const combinedLogs = normalized.logs.length ? normalized.logs : liveLogs;
          appendLogs(combinedLogs);
          setPendingRun((prev) =>
            prev
              ? {
                  ...prev,
                  runId: normalized.runId || prev.runId,
                  codeVersion: normalized.codeVersion ?? prev.codeVersion,
                  ok: normalized.ok,
                  error: normalized.error,
                  files: normalized.files,
                  logs: combinedLogs,
                  status: normalized.ok ? "completed" : "failed",
                }
              : prev
          );
          const targetRunId = normalized.runId;
          if (targetRunId) {
            void fetchRunHistory(selectedVariation.prefix).then((history) => {
              const exists = history.some((item) => item.id === targetRunId);
              if (exists) {
                setSelectedRunId(targetRunId);
                void fetchRunDetail(targetRunId).then(() => {
                  setPendingRun((prev) =>
                    prev && prev.runId === targetRunId ? null : prev
                  );
                });
              }
            });
          } else {
            void fetchRunHistory(selectedVariation.prefix);
          }
          return;
        }

        if (event.type === "error") {
          const detailText = formatRunError(
            event.detail,
            typeof event.message === "string" ? event.message : "Sandbox run failed."
          );
          setPendingRun((prev) =>
            prev ? { ...prev, status: "failed", error: detailText, ok: false } : prev
          );
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
      setPendingRun((prev) =>
        prev ? { ...prev, status: "failed", error: message, ok: false } : prev
      );
      setRunError(message);
    } finally {
      setIsRunning(false);
      if (selectedVariation) {
        void fetchRunHistory(selectedVariation.prefix);
      }
    }
  }, [
    selectedVariation,
    isRunning,
    currentCode,
    paramsText,
    pipPackages,
    currentVersion,
    toolApiBase,
    fetchRunHistory,
    fetchRunDetail,
  ]);

  const handleDeleteRun = useCallback(
    async (runId: string) => {
      if (!window.confirm("Delete this run and all associated files?")) {
        return;
      }
      if (pendingRun && (runId === pendingRun.tempId || runId === pendingRun.runId)) {
        window.alert("The active run cannot be deleted while it is in progress.");
        return;
      }
      try {
        const response = await fetch(`${toolApiBase}/e2b-runs/${runId}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          throw new Error(`Failed to delete run (${response.status})`);
        }
        if (selectedRunId === runId) {
          setSelectedRunId(null);
          setRunDetail(null);
        }
        if (selectedVariation) {
          await fetchRunHistory(selectedVariation.prefix);
        }
      } catch (error) {
        setHistoryError(
          error instanceof Error ? error.message : "Unable to delete run"
        );
      }
    },
    [pendingRun, toolApiBase, selectedRunId, selectedVariation, fetchRunHistory]
  );

  const handleSelectRun = useCallback(
    async (runId: string) => {
      setSelectedRunId(runId);
      if (pendingRun && runId === pendingRun.tempId) {
        return;
      }
      await fetchRunDetail(runId);
    },
    [fetchRunDetail, pendingRun]
  );

  const runFolderPrefixInfo = selectedVariation?.prefix ?? "uploads";

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Test variations</h1>
        <p className="text-sm text-muted-foreground">
          Run the current sandbox code against captured variation snapshots. Select a snapshot to
          inspect its files and execute the script using those inputs (no assistant required).
        </p>
      </header>

      <Card>
        <CardHeader className="flex items-center justify-between gap-2">
          <div>
            <CardTitle>Available variations</CardTitle>
            <CardDescription>
              Choose a snapshot to review its files and trigger sandbox runs.
            </CardDescription>
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => void loadVariations()}
            disabled={isLoadingVariations}
          >
            {isLoadingVariations ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" /> Refreshing…
              </>
            ) : (
              <>
                <RefreshCcw className="mr-2 size-4" /> Refresh
              </>
            )}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {variationsError && (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {variationsError}
            </p>
          )}
          {isLoadingVariations ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading variations…
            </div>
          ) : variations.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No variations captured yet. Use the evaluation tools to create variation snapshots.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {variations.map((variation) => {
                const isSelected = variation.id === selectedVariationId;
                return (
                  <button
                    key={variation.id}
                    type="button"
                    onClick={() => setSelectedVariationId(variation.id)}
                    className={cn(
                      "flex flex-col rounded-lg border px-4 py-3 text-left transition",
                      isSelected
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/40 hover:bg-muted/40"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold">
                        {variationTitle(variation)}
                      </h3>
                      <span className="text-xs uppercase tracking-wide text-muted-foreground">
                        {variation.id}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Created {formatDateTime(variation.created_at)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {variation.files.length} file{variation.files.length === 1 ? "" : "s"}
                    </p>
                  </button>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {selectedVariation ? (
        <div className="space-y-6">
          <div className="flex flex-col gap-4 lg:flex-row">
            <Card className="lg:w-80 lg:shrink-0">
              <CardHeader>
                <CardTitle>Snapshot files</CardTitle>
                <CardDescription>
                  Files bundled with <strong>{variationTitle(selectedVariation)}</strong>.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {selectedVariation.files.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    This snapshot does not include any files.
                  </p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {selectedVariation.files.map((file) => (
                      <li
                        key={file.path}
                        className="rounded-md border border-border bg-muted/20 px-3 py-2"
                      >
                        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span className="font-medium text-foreground">
                            {file.path}
                          </span>
                          <span>{formatBytes(file.size_bytes)}</span>
                        </div>
                        {file.filename && file.filename !== file.path && (
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            Original name: {file.filename}
                          </p>
                        )}
                        {file.modified_at && (
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            Saved {formatDateTime(file.modified_at)}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card className="flex-1">
              <CardHeader className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle>Run configuration</CardTitle>
                  <CardDescription>
                    Runs use variation prefix <code className="rounded bg-muted px-1 py-0.5 text-xs">{runFolderPrefixInfo}</code>.
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => void fetchCurrentCodeVersion()}
                    disabled={isCodeLoading}
                  >
                    {isCodeLoading ? (
                      <>
                        <Loader2 className="mr-2 size-4 animate-spin" /> Syncing…
                      </>
                    ) : (
                      <>
                        <RefreshCcw className="mr-2 size-4" /> Reload code
                      </>
                    )}
                  </Button>
                  <Button asChild size="sm" variant="ghost">
                    <Link to="../script">Open script</Link>
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {codeError && (
                  <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    {codeError}
                  </p>
                )}
                <div className="space-y-1 text-xs text-muted-foreground">
                  <p>
                    Code version {currentVersion ?? "?"} · {pipPackages.length} pip package
                    {pipPackages.length === 1 ? "" : "s"}
                  </p>
                  {pipPackages.length > 0 && (
                    <p>Pip: {pipPackages.join(", ")}</p>
                  )}
                  {paramSpecs.length > 0 && (
                    <p>Params: {paramSpecs.map((spec) => spec.name).join(", ")}</p>
                  )}
                  {requiredFiles.length > 0 && (
                    <p>Required files: {requiredFiles.map((item) => item.pattern).join(", ")}</p>
                  )}
                </div>

                <form
                  className="space-y-4"
                  onSubmit={(event: FormEvent<HTMLFormElement>) => {
                    event.preventDefault();
                    void handleRun();
                  }}
                >
                  <div className="space-y-2">
                    <Label htmlFor="variation-params">Run parameters (JSON)</Label>
                    <textarea
                      id="variation-params"
                      className="min-h-[160px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      value={paramsText}
                      onChange={(event) => setParamsText(event.target.value)}
                      spellCheck={false}
                    />
                  </div>
                  {runError && (
                    <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                      {runError}
                    </p>
                  )}
                  <Button type="submit" disabled={isRunning}>
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
                </form>
              </CardContent>
            </Card>
          </div>

          <div className="flex flex-col gap-4 lg:flex-row">
            <Card className="lg:w-72">
              <CardHeader>
                <CardTitle>Run history</CardTitle>
                <CardDescription>
                  Previous runs that used this variation snapshot.
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
                ) : combinedRunHistory.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No sandbox runs recorded yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {combinedRunHistory.map((run) => {
                      const isPendingEntry = pendingRun && run.id === pendingRun.tempId;
                      const isSelected =
                        selectedRunId === run.id ||
                        (isPendingEntry && selectedRunId === pendingRun?.tempId);
                      const statusLabel = isPendingEntry
                        ? pendingRun.status === "running"
                          ? "running"
                          : pendingRun.status === "failed"
                          ? "failed"
                          : "completed"
                        : run.ok == null
                        ? "unknown"
                        : run.ok
                        ? "success"
                        : "failure";
                      const statusClass = isPendingEntry
                        ? pendingRun.status === "failed"
                          ? "text-destructive"
                          : pendingRun.status === "completed"
                          ? "text-emerald-600"
                          : "text-muted-foreground"
                        : run.ok
                        ? "text-emerald-600"
                        : run.ok === false
                        ? "text-destructive"
                        : "text-muted-foreground";
                      const versionValue = isPendingEntry
                        ? pendingRun.codeVersion ?? currentVersion ?? undefined
                        : run.code_version;
                      const versionText =
                        typeof versionValue === "number" && Number.isFinite(versionValue)
                          ? versionValue
                          : "?";
                      const displayedError = isPendingEntry
                        ? pendingRun.error
                        : run.error;

                      return (
                        <li key={run.id}>
                          <div
                            role="button"
                            tabIndex={0}
                            className={cn(
                              "flex cursor-pointer flex-col rounded-md border px-3 py-2 text-sm transition",
                              isSelected
                                ? "border-primary bg-primary/10"
                                : "border-border hover:border-primary/40 hover:bg-muted/30"
                            )}
                            onClick={() => {
                              void handleSelectRun(run.id);
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                void handleSelectRun(run.id);
                              }
                            }}
                          >
                            <div className="flex items-center justify-between text-xs text-muted-foreground">
                              <span>{formatDateTime(run.created_at)}</span>
                              <span className="uppercase tracking-wide">v{versionText}</span>
                            </div>
                            <div className="mt-1 flex items-start justify-between gap-2 text-xs">
                              <span className={statusClass}>
                                {isPendingEntry && statusLabel === "running" && (
                                  <Loader2 className="mr-1 inline size-3 animate-spin" />
                                )}
                                {statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1)}
                              </span>
                              {displayedError && (
                                <span className="truncate text-destructive" title={displayedError}>
                                  {displayedError}
                                </span>
                              )}
                            </div>
                            {!isPendingEntry && (
                              <div className="mt-2 flex items-center justify-end">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-2 text-xs"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void handleDeleteRun(run.id);
                                  }}
                                >
                                  Delete
                                </Button>
                              </div>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card className="flex-1">
              <CardHeader>
                <CardTitle>Run details</CardTitle>
                <CardDescription>
                  {selectedRunIsPending
                    ? pendingRun?.runId ?? pendingRun?.tempId ?? "Pending run"
                    : selectedRunId ?? "Select a run to inspect logs and artifacts."}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {selectedRunIsPending && pendingRun ? (
                  <div className="space-y-4 text-sm">
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>{formatDateTime(pendingRun.created_at)}</span>
                      <span
                        className={cn(
                          pendingRun.status === "failed"
                            ? "text-destructive"
                            : pendingRun.status === "completed"
                            ? "text-emerald-600"
                            : "text-muted-foreground"
                        )}
                      >
                        {pendingRun.status === "running"
                          ? "Running"
                          : pendingRun.status === "failed"
                          ? "Failed"
                          : "Completed"}
                      </span>
                    </div>
                    {pendingRun.runId && (
                      <p className="text-xs text-muted-foreground">Run ID: {pendingRun.runId}</p>
                    )}
                    {pendingRun.codeVersion != null && (
                      <p className="text-xs text-muted-foreground">
                        Code version {pendingRun.codeVersion ?? "?"}
                      </p>
                    )}
                    {pendingRun.error && (
                      <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                        {pendingRun.error}
                      </p>
                    )}
                    <section className="space-y-2">
                      <h3 className="text-sm font-semibold">Logs</h3>
                      {pendingRun.logs.length === 0 ? (
                        <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                          No log output yet.
                        </p>
                      ) : (
                        <pre className="max-h-[320px] overflow-y-auto rounded-md border border-border bg-muted/30 p-3 text-xs">
                          {pendingRun.logs.join("\n")}
                        </pre>
                      )}
                    </section>
                    <section className="space-y-2">
                      <h3 className="text-sm font-semibold">Artifacts</h3>
                      {pendingRun.files.length === 0 ? (
                        <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                          No artifacts were produced during this run.
                        </p>
                      ) : (
                        <ul className="space-y-3 text-xs">
                          {pendingRun.files.map((file) => (
                            <li
                              key={file.path}
                              className="rounded-md border border-border bg-muted/30 p-3"
                            >
                              <div className="flex items-center justify-between gap-4 text-[11px] uppercase tracking-wide text-muted-foreground">
                                <span className="truncate font-medium normal-case text-foreground">
                                  {file.path}
                                </span>
                                <span>{formatBytes(file.sizeBytes)}</span>
                              </div>
                              {file.preview && (
                                <pre className="mt-2 max-h-[160px] overflow-y-auto rounded-md border border-border bg-background/80 p-2 text-[11px]">
                                  {file.preview}
                                </pre>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </section>
                  </div>
                ) : selectedRunId ? (
                  runDetailError ? (
                    <p className="text-sm text-muted-foreground">{runDetailError}</p>
                  ) : isRunDetailLoading ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="size-4 animate-spin" /> Loading run details…
                    </div>
                  ) : runDetail ? (
                    <div className="space-y-4 text-sm">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>{formatDateTime(runDetail.created_at)}</span>
                        <span>
                          Version {runDetail.code_version} · {runDetail.allow_internet ? "Internet enabled" : "Offline"}
                        </span>
                      </div>
                      {runDetail.error && (
                        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {runDetail.error}
                        </p>
                      )}
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
                  ) : runError ? (
                    <p className="text-sm text-muted-foreground">{runError}</p>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Select a run to view details.
                    </p>
                  )
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Select a run to inspect logs and artifacts.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Select a variation snapshot to review its files and run the sandbox.
        </p>
      )}
    </div>
  );
}
