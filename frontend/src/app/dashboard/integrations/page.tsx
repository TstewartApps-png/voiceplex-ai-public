"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Calendar, Mail, CheckCircle, XCircle, AlertCircle } from "lucide-react";
import api from "@/lib/api";
import { Company } from "@/types";

type Provider = "google" | "microsoft";

export default function IntegrationsPage() {
  const searchParams = useSearchParams();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const company = companies.find((c) => c.id === companyId) || null;

  useEffect(() => {
    fetchCompanies();
  }, []);

  // Feedback after the OAuth round-trip (backend redirects back here with query params)
  useEffect(() => {
    const error = searchParams.get("error");
    const email = searchParams.get("email");
    if (searchParams.get("google_connected")) {
      setMessage({ type: "success", text: `Google Workspace connected${email ? ` as ${email}` : ""}` });
    } else if (searchParams.get("microsoft_connected")) {
      setMessage({ type: "success", text: `Microsoft 365 connected${email ? ` as ${email}` : ""}` });
    } else if (error) {
      setMessage({ type: "error", text: `Connection failed: ${error.replace(/_/g, " ")}` });
    }
  }, [searchParams]);

  const fetchCompanies = async () => {
    try {
      const response = await api.get("/companies");
      const data: Company[] = Array.isArray(response.data) ? response.data : response.data.items || [];
      setCompanies(data);
      setCompanyId((current) => current || (data[0]?.id ?? ""));
    } catch (error) {
      console.error("Failed to fetch companies:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleConnect = async (provider: Provider) => {
    if (!companyId) return;
    setMessage(null);
    try {
      const response = await api.get(`/integrations/${provider}/auth-url`, {
        params: {
          company_id: companyId,
          redirect_after: `${window.location.origin}/dashboard/integrations`,
        },
      });
      if (response.data.auth_url) {
        window.location.href = response.data.auth_url;
      }
    } catch (error: any) {
      const code = error.response?.data?.code;
      setMessage({
        type: "error",
        text:
          code === "GOOGLE_NOT_CONFIGURED" || code === "MICROSOFT_NOT_CONFIGURED"
            ? `${provider === "google" ? "Google" : "Microsoft"} OAuth is not configured on the server (set the CLIENT_ID / CLIENT_SECRET environment variables).`
            : error.response?.data?.detail || `Failed to start ${provider} sign-in`,
      });
    }
  };

  const handleDisconnect = async (provider: Provider) => {
    if (!companyId) return;
    setMessage(null);
    try {
      await api.post(`/integrations/${provider}/disconnect`, null, { params: { company_id: companyId } });
      await fetchCompanies();
    } catch (error: any) {
      setMessage({ type: "error", text: error.response?.data?.detail || `Failed to disconnect ${provider}` });
    }
  };

  const integrations = [
    {
      id: "google",
      name: "Google Workspace",
      description: "Connect Google Calendar and Gmail for scheduling and notifications",
      icon: Calendar,
      connected: company?.integrations?.google?.connected || false,
      email: company?.integrations?.google?.email,
      onConnect: () => handleConnect("google"),
      onDisconnect: () => handleDisconnect("google"),
      features: ["Calendar scheduling", "Gmail notifications", "Contact sync"],
    },
    {
      id: "microsoft",
      name: "Microsoft 365",
      description: "Connect Outlook Calendar and Email for scheduling and notifications",
      icon: Mail,
      connected: company?.integrations?.microsoft?.connected || false,
      email: company?.integrations?.microsoft?.email,
      onConnect: () => handleConnect("microsoft"),
      onDisconnect: () => handleDisconnect("microsoft"),
      features: ["Outlook Calendar", "Email notifications", "Teams integration"],
    },
  ];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading integrations...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Integrations</h1>
        <p className="text-muted-foreground mt-1">
          Connect your tools to enhance your AI agents
        </p>
      </div>

      {companies.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          Create a company first — integrations are connected per company.
        </div>
      ) : (
        <div className="max-w-sm space-y-2">
          <Label htmlFor="integration-company">Company</Label>
          <select
            id="integration-company"
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={companyId}
            onChange={(e) => setCompanyId(e.target.value)}
          >
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {message && (
        <div
          className={`rounded-md p-3 text-sm flex items-center gap-2 ${
            message.type === "success"
              ? "bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-400"
              : "bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400"
          }`}
        >
          {message.type === "success" ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
          {message.text}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {integrations.map((integration) => (
          <Card key={integration.id}>
            <CardHeader>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
                    <integration.icon className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <CardTitle>{integration.name}</CardTitle>
                    <CardDescription className="mt-1">
                      {integration.description}
                    </CardDescription>
                  </div>
                </div>
                {integration.connected ? (
                  <Badge className="bg-green-500">
                    <CheckCircle className="mr-1 h-3 w-3" />
                    Connected
                  </Badge>
                ) : (
                  <Badge variant="secondary">
                    <XCircle className="mr-1 h-3 w-3" />
                    Not Connected
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {integration.connected && integration.email && (
                <div className="rounded-lg bg-secondary p-3">
                  <p className="text-sm font-medium">Connected Account</p>
                  <p className="text-sm text-muted-foreground">{integration.email}</p>
                </div>
              )}

              <div>
                <p className="text-sm font-medium mb-2">Features</p>
                <ul className="space-y-1">
                  {integration.features.map((feature, idx) => (
                    <li key={idx} className="text-sm text-muted-foreground flex items-center gap-2">
                      <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                      {feature}
                    </li>
                  ))}
                </ul>
              </div>

              {integration.connected ? (
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={integration.onDisconnect}
                >
                  Disconnect
                </Button>
              ) : (
                <Button className="w-full" onClick={integration.onConnect} disabled={!companyId}>
                  Connect {integration.name}
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
