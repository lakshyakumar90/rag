"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthGuard } from "../../../components/auth-guard";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { api } from "../../../lib/api/client";

function AcceptInvitation() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token");
  const [message, setMessage] = useState("Accepting invitation…");

  useEffect(() => {
    if (!token) {
      setMessage("Missing invitation token.");
      return;
    }
    api
      .acceptInvitation(token)
      .then((workspace) => {
        setMessage(`Joined ${workspace.name}`);
        router.push(`/workspaces/${workspace.id}/documents`);
      })
      .catch((error) =>
        setMessage(error instanceof Error ? error.message : "Could not accept invitation"),
      );
  }, [token, router]);

  return (
    <Card className="mx-auto max-w-lg">
      <CardHeader><CardTitle>Invitation</CardTitle></CardHeader>
      <CardContent>
        <p className="mb-4">{message}</p>
        <Button onClick={() => router.push("/dashboard")}>Back to dashboard</Button>
      </CardContent>
    </Card>
  );
}

export default function AcceptInvitationPage() {
  return <AuthGuard><AcceptInvitation /></AuthGuard>;
}
