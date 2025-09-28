import { useCallback, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useLoaderData } from "react-router";

import { Button } from "~/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "~/components/ui/card";

import { API_BASE_URL } from "../config";
import type { Route } from "./+types/_app.tool_test";


type ToolExecution = {
  tool_call: Record<string, unknown>;
  output: Record<string, unknown>;
};

type ToolInvocationPayload = {
  tool: Record<string, unknown>;
  assistant_text: string;
  response: Record<string, unknown>;
  usage: Record<string, unknown> | null;
  raw_text: string;
  pip_packages: unknown[];
  params: Record<string, unknown>[];
  required_files: Record<string, unknown>[];
  executions: ToolExecution[];
};

type LoaderResult = {
  ok: boolean;
  payload: ToolInvocationPayload | null;
  error?: string;
};

export async function loader({}: Route.LoaderArgs) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/tool-test`, {
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      return {
        ok: false,
        payload: null,
        error: `Backend responded with ${response.status}`,
      } satisfies LoaderResult;
    }

    const payload = (await response.json()) as ToolInvocationPayload;
    return { ok: true, payload } satisfies LoaderResult;
  } catch (error) {
    return {
      ok: false,
      payload: null,
      error:
        error instanceof Error
          ? error.message
          : "Unable to reach tool test endpoint",
    } satisfies LoaderResult;
  }
}

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Tool Test | XLS Workspace" },
    {
      name: "description",
      content: "Validate Responses tool scaffolding with a hello world invocation.",
    },
  ];
}

export default function ToolTestRoute() {
  const initial = useLoaderData<typeof loader>();
  const [state, setState] = useState(() => ({
    loading: false,
    ok: initial.ok,
    payload: initial.payload,
    error: initial.error ?? null,
  }));

  const handleRun = useCallback(async () => {
    try {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      const response = await fetch(`${API_BASE_URL}/api/tool-test`, {
        headers: { "Content-Type": "application/json" },
      });

      if (!response.ok) {
        throw new Error(`Backend responded with ${response.status}`);
      }

      const payload = (await response.json()) as ToolInvocationPayload;
      setState({ loading: false, ok: true, payload, error: null });
    } catch (error) {
      setState({
        loading: false,
        ok: false,
        payload: null,
        error:
          error instanceof Error
            ? error.message
            : "Unable to reach tool test endpoint",
      });
    }
  }, []);

  const { loading, payload, error } = state;

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold">Tool Test Harness</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Trigger the built-in <code>hello_world</code> tool and inspect the
          artefacts we store for the OpenAI Responses API.
        </p>
      </header>

      <div className="flex gap-3">
        <Button onClick={handleRun} disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Running...
            </>
          ) : (
            <>
              <RefreshCw className="mr-2 h-4 w-4" /> Run tool
            </>
          )}
        </Button>
      </div>

      {error && (
        <Card className="border-destructive/50 bg-destructive/10">
          <CardHeader>
            <CardTitle className="text-destructive">Unable to run tool</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {payload && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>Execution Summary</CardTitle>
              <CardDescription>
                {payload.executions.length} tool call
                {payload.executions.length === 1 ? "" : "s"} captured
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <p>
                <span className="font-semibold">Assistant:</span> {payload.assistant_text}
              </p>
              {payload.usage && (
                <pre className="rounded-md bg-muted p-3">
                  {JSON.stringify(payload.usage, null, 2)}
                </pre>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Tool Definition</CardTitle>
              <CardDescription>Sent as <code>FunctionToolParam</code>.</CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="rounded-md bg-muted p-3 text-xs leading-relaxed">
                {JSON.stringify(payload.tool, null, 2)}
              </pre>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Tool Call</CardTitle>
              <CardDescription>Matches <code>ResponseFunctionToolCallParam</code>.</CardDescription>
            </CardHeader>
            <CardContent>
              {payload.executions.length > 0 ? (
                <pre className="rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {JSON.stringify(payload.executions[0]?.tool_call ?? null, null, 2)}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground">No tool call returned.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Tool Output</CardTitle>
              <CardDescription>Structured as <code>ResponseInputItemParam</code>.</CardDescription>
            </CardHeader>
            <CardContent>
              {payload.executions.length > 0 ? (
                <pre className="rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {JSON.stringify(payload.executions[0]?.output ?? null, null, 2)}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground">No tool output captured.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Raw Response</CardTitle>
              <CardDescription>Inspect the full assistant output.</CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="rounded-md bg-muted p-3 text-xs leading-relaxed">
                {payload.raw_text}
              </pre>
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>Response Metadata</CardTitle>
              <CardDescription>Includes pip packages, params, and raw response object.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-2">
              <div>
                <h3 className="text-xs font-semibold uppercase text-muted-foreground">pip packages</h3>
                <pre className="mt-2 rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {JSON.stringify(payload.pip_packages, null, 2)}
                </pre>
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase text-muted-foreground">params model</h3>
                <pre className="mt-2 rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {JSON.stringify(payload.params, null, 2)}
                </pre>
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase text-muted-foreground">required files</h3>
                <pre className="mt-2 rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {JSON.stringify(payload.required_files, null, 2)}
                </pre>
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase text-muted-foreground">response object</h3>
                <pre className="mt-2 rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {JSON.stringify(payload.response, null, 2)}
                </pre>
              </div>
              <div className="md:col-span-2">
                <h3 className="text-xs font-semibold uppercase text-muted-foreground">executions</h3>
                <pre className="mt-2 rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {JSON.stringify(payload.executions, null, 2)}
                </pre>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
