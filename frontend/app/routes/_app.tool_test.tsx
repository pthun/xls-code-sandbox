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


type ToolCallResult = {
  success: boolean;
  output?: unknown;
  error?: string | null;
};

type ToolInvocationPayload = {
  assistant_text: string;
  raw_text: string;
  tool_result: ToolCallResult | null;
};

type LoaderResult = {
  ok: boolean;
  payload: ToolInvocationPayload | null;
  error?: string;
};

function formatToolOutput(output: unknown): string | null {
  if (output === undefined || output === null) {
    return null;
  }

  if (typeof output === "string") {
    return output;
  }

  try {
    return JSON.stringify(output, null, 2);
  } catch (error) {
    return String(output);
  }
}

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
  const toolOutputText = formatToolOutput(payload?.tool_result?.output);

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
              <CardTitle>Assistant Summary</CardTitle>
              <CardDescription>Text returned after the tool call finished.</CardDescription>
            </CardHeader>
            <CardContent className="text-sm leading-relaxed">
              {payload.assistant_text}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Tool Result</CardTitle>
              <CardDescription>Status reported by the backend.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              {payload.tool_result ? (
                <>
                  <p>
                    <span className="font-semibold">Status:</span>{" "}
                    {payload.tool_result.success ? "Success" : "Failure"}
                  </p>
                  {payload.tool_result.error ? (
                    <p className="text-destructive">
                      <span className="font-semibold">Error:</span> {payload.tool_result.error}
                    </p>
                  ) : null}
                  {toolOutputText ? (
                    <pre className="rounded-md bg-muted p-3 text-xs leading-relaxed">
                      {toolOutputText}
                    </pre>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      No tool output returned.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  No tool execution recorded.
                </p>
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
        </div>
      )}
    </div>
  );
}
