import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { Loading } from "@/components/irm/states";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Inventory Risk Monitor" },
      { name: "description", content: "Monitor material shortage risk across plant projects." },
      { property: "og:title", content: "Inventory Risk Monitor" },
      { property: "og:description", content: "Monitor material shortage risk across plant projects." },
    ],
  }),
  component: Index,
});

function Index() {
  const { session, ready } = useAuth();
  const navigate = useNavigate();
  useEffect(() => {
    if (ready) navigate({ to: session ? "/overview" : "/login", replace: true });
  }, [ready, session, navigate]);
  return <Loading />;
}
