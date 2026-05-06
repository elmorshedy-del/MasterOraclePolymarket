export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type ProxyContext = {
  params: {
    path?: string[];
  };
};

const HOP_BY_HOP_HEADERS = [
  "connection",
  "content-encoding",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

function backendBaseUrl() {
  return (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/+$/, "");
}

function buildBackendUrl(request: Request, context: ProxyContext) {
  const path = context.params.path?.map((segment) => encodeURIComponent(segment)).join("/") ?? "";
  const target = new URL(`${backendBaseUrl()}/${path}`);
  target.search = new URL(request.url).search;
  return target;
}

function forwardedHeaders(request: Request) {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

function responseHeaders(source: Headers) {
  const headers = new Headers(source);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

async function proxyBackend(request: Request, context: ProxyContext) {
  const target = buildBackendUrl(request, context);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  try {
    const response = await fetch(target, {
      method: request.method,
      headers: forwardedHeaders(request),
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders(response.headers),
    });
  } catch (error) {
    console.error(`Backend proxy failed for ${target.toString()}`, error);
    const message = error instanceof Error ? error.message : "Unknown proxy error";
    return Response.json(
      { error: "backend_proxy_failed", message },
      { status: 502 },
    );
  }
}

export function GET(request: Request, context: ProxyContext) {
  return proxyBackend(request, context);
}

export function POST(request: Request, context: ProxyContext) {
  return proxyBackend(request, context);
}

export function PUT(request: Request, context: ProxyContext) {
  return proxyBackend(request, context);
}

export function PATCH(request: Request, context: ProxyContext) {
  return proxyBackend(request, context);
}

export function DELETE(request: Request, context: ProxyContext) {
  return proxyBackend(request, context);
}

export function OPTIONS(request: Request, context: ProxyContext) {
  return proxyBackend(request, context);
}
