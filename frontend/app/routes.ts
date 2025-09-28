import { type RouteConfig, index, layout, route } from "@react-router/dev/routes";

export default [
  layout("routes/_app.tsx", [
    index("routes/_app._index.tsx"),
    route("tool_test", "routes/_app.tool_test.tsx"),
    route("tools/:toolId", "routes/_app.tools.tsx", { id: "tools-layout" }, [
      index("routes/_app.tools.$toolId.tsx"),
      route("files", "routes/_app.tools.$toolId.files.tsx"),
      route("script", "routes/_app.tools.$toolId.script.tsx"),
      route(
        "generate-eval-files",
        "routes/_app.tools.$toolId.generate-eval-files.tsx"
      ),
    ]),
  ]),
] satisfies RouteConfig;
