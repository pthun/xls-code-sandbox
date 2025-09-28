import { type RouteConfig, index, layout, route } from "@react-router/dev/routes";

export default [
  layout("routes/_app.tsx", [
    index("routes/_app._index.tsx"),
    route("e2b-test", "routes/_app.e2b-test.tsx"),
    route("tool_test", "routes/_app.tool_test.tsx"),
    route("tools/:toolId", "routes/_app.tools.tsx", { id: "tools-layout" }, [
      index("routes/_app.tools.$toolId.tsx"),
      route("files", "routes/_app.tools.$toolId.files.tsx"),
    ]),
  ]),
] satisfies RouteConfig;
