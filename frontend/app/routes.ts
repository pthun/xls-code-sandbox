import { type RouteConfig, index, layout, route } from "@react-router/dev/routes";

export default [
  layout("routes/_app.tsx", [
    index("routes/_app._index.tsx"),
    route("e2b-test", "routes/_app.e2b-test.tsx"),
    route("tools/:toolId", "routes/_app.tools.$toolId.tsx"),
  ]),
] satisfies RouteConfig;
