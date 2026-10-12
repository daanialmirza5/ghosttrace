import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

type Handler = (init: RequestInit | undefined, url: URL) => { status?: number; body?: unknown; headers?: Record<string, string> };

export interface MockedCall {
  method: string;
  url: URL;
  init: RequestInit | undefined;
}

/** Route fetch calls to handlers keyed by "METHOD /path" (path without /api/v1). */
export function mockApi(routes: Record<string, Handler | object>) {
  const calls: MockedCall[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, url, init });
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const match = Object.entries(routes).find(([key]) => {
      const [m, pattern] = key.split(" ");
      return m === method && new RegExp(`^${pattern!.replace(/:[a-z_]+/g, "[^/]+")}$`).test(path);
    });
    if (!match) return new Response(JSON.stringify({ error: { code: "not_found", message: `unmocked ${method} ${path}` } }), { status: 404 });
    const handler = match[1];
    const isSpec = typeof handler === "object" && handler !== null && "status" in handler && "body" in handler;
    const result =
      typeof handler === "function"
        ? (handler as Handler)(init, url)
        : isSpec
          ? (handler as { status: number; body: unknown; headers?: Record<string, string> })
          : { body: handler };
    return new Response(result.body === undefined ? null : JSON.stringify(result.body), {
      status: result.status ?? 200,
      headers: { "Content-Type": "application/json", ...result.headers },
    });
  });
  return { calls, spy };
}

export function renderWithProviders(ui: ReactElement, { route = "/", path = "*" }: { route?: string; path?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
