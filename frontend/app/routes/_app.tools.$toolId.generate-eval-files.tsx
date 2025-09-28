import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Loader2, Send, Trash2 } from "lucide-react";
import { useOutletContext } from "react-router";

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
import { cn } from "~/lib/utils";

import { API_BASE_URL } from "../config";
import type { ToolLayoutContextValue } from "./_app.tools";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type ChatUsage = {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
} | null;

type EvalChatResponse = {
  message: {
    role: "assistant";
    content: string;
  };
  usage?: ChatUsage;
  raw?: string | null;
};

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

const DEFAULT_FOLDER_PREFIX = "uploads";

function createId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

function createInitialAssistantMessage(): ChatMessage {
  return {
    id: createId(),
    role: "assistant",
    content:
      "Hi! Describe how you’d like to transform your uploaded files—add columns, create variants, or craft edge cases. I can inspect files with the available tools and outline the steps to produce the new evaluation data.",
  };
}

export default function GenerateEvalFilesView() {
  const { tool } = useOutletContext<ToolLayoutContextValue>();
  const toolApiBase = useMemo(() => `${API_BASE_URL}/api/tools/${tool.id}`, [tool.id]);
  const chatHistoryUrl = useMemo(
    () => `${toolApiBase}/eval-chat/history`,
    [toolApiBase]
  );

  const [variations, setVariations] = useState<Variation[]>([]);
  const [isLoadingVariations, setIsLoadingVariations] = useState(false);
  const [variationsError, setVariationsError] = useState<string | null>(null);
  const [isCreatingVariation, setIsCreatingVariation] = useState(false);
  const [folderPrefix, setFolderPrefix] = useState<string>(DEFAULT_FOLDER_PREFIX);
  const activeVariation = useMemo(
    () => variations.find((item) => item.prefix === folderPrefix) ?? null,
    [variations, folderPrefix]
  );
  const activeVariationLabel = useMemo(() => {
    if (!activeVariation) return null;
    return activeVariation.label?.trim() || `Variation ${activeVariation.id}`;
  }, [activeVariation]);
  const isVariationWorkspace = folderPrefix !== DEFAULT_FOLDER_PREFIX;

  const [messages, setMessages] = useState<ChatMessage[]>(() => [
    createInitialAssistantMessage(),
  ]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<ChatUsage>(null);
  const [isClearing, setIsClearing] = useState(false);

  const persistChatHistory = useCallback(
    async (entries: ChatMessage[]) => {
      try {
        const response = await fetch(chatHistoryUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: entries }),
        });
        if (!response.ok) {
          throw new Error(`Persist failed (${response.status})`);
        }
      } catch (persistError) {
        console.error("Failed to persist eval chat history", persistError);
      }
    },
    [chatHistoryUrl]
  );

  const appendMessages = useCallback(
    (addition: ChatMessage | ChatMessage[]) => {
      setMessages((prev) => {
        const additions = Array.isArray(addition) ? addition : [addition];
        const next = [...prev, ...additions];
        void persistChatHistory(next);
        return next;
      });
    },
    [persistChatHistory]
  );

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
      const payload = (await response.json()) as Variation[];
      if (Array.isArray(payload)) {
        setVariations(payload);
      } else {
        setVariations([]);
      }
    } catch (variationError) {
      console.error("Failed to load variations", variationError);
      setVariations([]);
      setVariationsError(
        variationError instanceof Error
          ? variationError.message
          : "Failed to load variations"
      );
    } finally {
      setIsLoadingVariations(false);
    }
  }, [toolApiBase]);

  useEffect(() => {
    void loadVariations();
  }, [loadVariations]);

  const handleCreateVariation = useCallback(async () => {
    const labelInput = window.prompt("Name for the new variation (optional)", "");
    if (labelInput === null) {
      return;
    }
    const label = labelInput ? labelInput.trim() : null;

    setIsCreatingVariation(true);
    setVariationsError(null);
    try {
      const response = await fetch(`${toolApiBase}/variations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      if (!response.ok) {
        let detail = `Failed to create variation (${response.status})`;
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) detail = payload.detail;
        } catch (error) {
          console.error(error);
        }
        throw new Error(detail);
      }

      const created = (await response.json()) as Variation;
      setVariations((prev) => [created, ...prev.filter((item) => item.id !== created.id)]);
      setFolderPrefix(created.prefix);
    } catch (creationError) {
      console.error("Failed to create variation", creationError);
      setVariationsError(
        creationError instanceof Error
          ? creationError.message
          : "Failed to create variation"
      );
    } finally {
      setIsCreatingVariation(false);
      void loadVariations();
    }
  }, [toolApiBase, loadVariations]);

  const loadChatHistory = useCallback(async () => {
    try {
      const response = await fetch(chatHistoryUrl, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        if (response.status === 404) {
          setMessages([createInitialAssistantMessage()]);
          return;
        }
        throw new Error(`History load failed (${response.status})`);
      }
      const history = (await response.json()) as ChatMessage[];
      if (Array.isArray(history) && history.length > 0) {
        setMessages(history);
      } else {
        setMessages([createInitialAssistantMessage()]);
      }
    } catch (loadError) {
      console.error("Failed to load eval chat history", loadError);
      setMessages([createInitialAssistantMessage()]);
    }
  }, [chatHistoryUrl]);

  useEffect(() => {
    setMessages([createInitialAssistantMessage()]);
    setInput("");
    setError(null);
    setUsage(null);
    setIsSending(false);
    setIsClearing(false);
    void loadChatHistory();
  }, [tool.id, loadChatHistory]);

  useEffect(() => {
    setMessages([createInitialAssistantMessage()]);
    setInput("");
    setUsage(null);
    setError(null);
    setIsSending(false);
    setIsClearing(false);
  }, [folderPrefix]);

  const handleClearChat = useCallback(async () => {
    if (isClearing) {
      return;
    }
    setIsClearing(true);
    setError(null);
    try {
      const response = await fetch(chatHistoryUrl, {
        method: "DELETE",
      });
      if (!response.ok && response.status !== 404) {
        throw new Error(`Failed to clear chat (${response.status})`);
      }
      setMessages([createInitialAssistantMessage()]);
      setUsage(null);
    } catch (clearError) {
      setError(
        clearError instanceof Error
          ? clearError.message
          : "Unable to clear chat history"
      );
    } finally {
      setIsClearing(false);
    }
  }, [chatHistoryUrl, isClearing]);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (isSending) {
        return;
      }
      const trimmed = input.trim();
      if (!trimmed) {
        return;
      }

      const userMessage: ChatMessage = {
        id: createId(),
        role: "user",
        content: trimmed,
      };
      const nextMessages = [...messages, userMessage];
      const historyPayload = nextMessages.map(({ role, content }) => ({ role, content }));

      appendMessages(userMessage);
      setInput("");
      setIsSending(true);
      setError(null);

      try {
        const response = await fetch(`${toolApiBase}/eval-chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: historyPayload, folder_prefix: folderPrefix }),
        });
        if (!response.ok) {
          let detail = `Request failed (${response.status})`;
          try {
            const payload = (await response.json()) as { detail?: string };
            if (payload?.detail) detail = payload.detail;
          } catch (parseError) {
            console.error(parseError);
          }
          throw new Error(detail);
        }

        const data = (await response.json()) as EvalChatResponse;
        const assistantContent = data?.message?.content?.trim() || "No response.";
        const assistantMessage: ChatMessage = {
          id: createId(),
          role: "assistant",
          content: assistantContent,
        };
        appendMessages(assistantMessage);
        setUsage(data.usage ?? null);
      } catch (sendError) {
        setError(sendError instanceof Error ? sendError.message : "Chat request failed");
      } finally {
        setIsSending(false);
      }
    },
    [appendMessages, folderPrefix, input, isSending, messages, toolApiBase]
  );

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Generate Eval Files</h1>
        <p className="text-sm text-muted-foreground">
          Collaborate with the assistant to design new evaluation datasets derived from your
          uploaded files.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Workspace</CardTitle>
          <CardDescription>
            Choose the workspace the assistant should use for file operations.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2">
            <Label htmlFor="workspace-select">Active workspace</Label>
            <select
              id="workspace-select"
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              value={folderPrefix}
              onChange={(event) => setFolderPrefix(event.target.value)}
              disabled={isLoadingVariations || isCreatingVariation}
            >
              <option value={DEFAULT_FOLDER_PREFIX}>Original uploads (read-only)</option>
              {variations.map((variation) => {
                const label = variation.label?.trim() || `Variation ${variation.id}`;
                return (
                  <option key={variation.id} value={variation.prefix}>
                    {label}
                  </option>
                );
              })}
            </select>
          </div>
          {variationsError && (
            <p className="text-xs text-destructive">{variationsError}</p>
          )}
          {isLoadingVariations && !isCreatingVariation && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3 animate-spin" /> Loading variations…
            </p>
          )}
          {isVariationWorkspace ? (
            <p className="text-xs text-muted-foreground">
              Working in {activeVariationLabel || folderPrefix}. Edits will only affect files inside this
              variation directory.
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Uploads are read-only. Create and select a variation to make inline edits safely.
            </p>
          )}
        </CardContent>
        <CardFooter className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setFolderPrefix(DEFAULT_FOLDER_PREFIX)}
            disabled={!isVariationWorkspace}
          >
            Use uploads
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleCreateVariation}
            disabled={isLoadingVariations || isCreatingVariation}
          >
            {isCreatingVariation ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" /> Working…
              </>
            ) : (
              <>New variation</>
            )}
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle>Assistant conversation</CardTitle>
              <CardDescription>
                Ask for dataset variations, call tools to inspect inputs, and capture the proposed
                outputs in plain language.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleClearChat}
              disabled={isClearing}
            >
              {isClearing ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" /> Clearing…
                </>
              ) : (
                <>
                  <Trash2 className="mr-2 size-4" /> Clear chat
                </>
              )}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3">
            {messages.map((message) => {
              const isAssistant = message.role === "assistant";
              const bubbleStyles = cn(
                "max-w-full whitespace-pre-wrap rounded-md border px-3 py-2 text-sm",
                isAssistant
                  ? "self-start bg-muted text-muted-foreground"
                  : "self-end bg-primary text-primary-foreground"
              );
              const label = isAssistant ? "Assistant" : "You";

              return (
                <div key={message.id} className={bubbleStyles}>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {label}
                  </div>
                  <div>{message.content}</div>
                </div>
              );
            })}
            {isSending && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Thinking…
              </div>
            )}
          </div>
          {error && (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
        </CardContent>
        <CardFooter>
          <form onSubmit={handleSubmit} className="flex w-full flex-col gap-3">
            <textarea
              className="min-h-[120px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="Explain the evaluation scenario or describe the file edits you need."
              value={input}
              onChange={(event) => setInput(event.target.value)}
              disabled={isSending}
            />
            <div className="flex items-center justify-between gap-3">
              {usage && (
                <p className="text-xs text-muted-foreground">
                  Tokens — prompt: {usage.prompt_tokens ?? "?"}, completion: {usage.completion_tokens ?? "?"},
                  total: {usage.total_tokens ?? "?"}
                </p>
              )}
              <Button type="submit" className="ml-auto" disabled={isSending || !input.trim()}>
                {isSending ? (
                  <>
                    <Loader2 className="mr-2 size-4 animate-spin" /> Sending…
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
    </section>
  );
}
