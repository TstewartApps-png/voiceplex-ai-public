"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthStore } from "@/stores/authStore";
import api from "@/lib/api";
import {
  User,
  Bell,
  Plug,
  Mic,
  Phone,
  Brain,
  Eye,
  EyeOff,
  CheckCircle,
  XCircle,
  Loader2,
  AlertCircle,
  ExternalLink,
} from "lucide-react";

interface IntegrationStatus {
  personaplex: { connected: boolean; url?: string };
  twilio: { connected: boolean; phone_number?: string; agent_id?: string | null; webhook_configured?: boolean };
  anthropic: { connected: boolean; has_key?: boolean };
}

interface AgentOption {
  id: string;
  name: string;
  status: string;
}

export default function SettingsPage() {
  const { user, setUser } = useAuthStore();
  const [isLoading, setIsLoading] = useState(false);
  const [name, setName] = useState(user?.name || "");
  const [email, setEmail] = useState(user?.email || "");
  const [success, setSuccess] = useState("");

  // Integration states
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);

  // PersonaPlex
  const [personaplexUrl, setPersonaplexUrl] = useState("");
  const [personaplexSaving, setPersonaplexSaving] = useState(false);
  const [personaplexTesting, setPersonaplexTesting] = useState(false);
  const [personaplexMessage, setPersonaplexMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Twilio
  const [twilioAccountSid, setTwilioAccountSid] = useState("");
  const [twilioAuthToken, setTwilioAuthToken] = useState("");
  const [twilioPhoneNumber, setTwilioPhoneNumber] = useState("");
  const [twilioAgentId, setTwilioAgentId] = useState("");
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [showTwilioToken, setShowTwilioToken] = useState(false);
  const [twilioSaving, setTwilioSaving] = useState(false);
  const [twilioTesting, setTwilioTesting] = useState(false);
  const [twilioMessage, setTwilioMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Anthropic
  const [anthropicApiKey, setAnthropicApiKey] = useState("");
  const [showAnthropicKey, setShowAnthropicKey] = useState(false);
  const [anthropicSaving, setAnthropicSaving] = useState(false);
  const [anthropicTesting, setAnthropicTesting] = useState(false);
  const [anthropicMessage, setAnthropicMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Load integration status on mount
  useEffect(() => {
    loadIntegrationStatus();
    api
      .get("/agents")
      .then((r) => {
        const data = Array.isArray(r.data) ? r.data : r.data.items || [];
        setAgents(data.map((a: any) => ({ id: a.id, name: a.name, status: a.status })));
      })
      .catch(() => setAgents([]));
  }, []);

  const loadIntegrationStatus = async () => {
    setLoadingStatus(true);
    try {
      const response = await api.get("/settings/integrations");
      setIntegrationStatus(response.data);
      if (response.data?.twilio?.phone_number && !twilioPhoneNumber) {
        setTwilioPhoneNumber(response.data.twilio.phone_number);
      }
      if (response.data?.twilio?.agent_id) {
        setTwilioAgentId(response.data.twilio.agent_id);
      }

      // Pre-fill PersonaPlex URL if available
      if (response.data.personaplex?.url) {
        setPersonaplexUrl(response.data.personaplex.url);
      }

      // Pre-fill Twilio phone number if available (don't show credentials)
      if (response.data.twilio?.phone_number) {
        setTwilioPhoneNumber(response.data.twilio.phone_number);
      }
    } catch (error) {
      console.error("Failed to load integration status:", error);
    } finally {
      setLoadingStatus(false);
    }
  };

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setSuccess("");

    try {
      const response = await api.put("/settings/profile", {
        name,
        email,
      });
      setUser({ ...user!, name: response.data.name, email: response.data.email });
      setSuccess("Profile updated successfully");
    } catch (error: any) {
      console.error("Failed to update profile:", error);
      const message = error.response?.data?.detail?.detail || "Failed to update profile";
      alert(message);
    } finally {
      setIsLoading(false);
    }
  };

  // PersonaPlex handlers
  const handleSavePersonaplex = async () => {
    setPersonaplexSaving(true);
    setPersonaplexMessage(null);
    try {
      await api.post("/settings/personaplex", { websocket_url: personaplexUrl });
      setPersonaplexMessage({ type: "success", text: "PersonaPlex URL saved successfully" });
      loadIntegrationStatus();
    } catch (error: any) {
      setPersonaplexMessage({
        type: "error",
        text: error.response?.data?.detail || "Failed to save PersonaPlex URL",
      });
    } finally {
      setPersonaplexSaving(false);
    }
  };

  const handleTestPersonaplex = async () => {
    setPersonaplexTesting(true);
    setPersonaplexMessage(null);
    try {
      const response = await api.post("/settings/personaplex/test", { websocket_url: personaplexUrl });
      if (response.data.success) {
        setPersonaplexMessage({ type: "success", text: `Connected! Latency: ${response.data.latency_ms}ms` });
        // Refresh integration status to update UI state after successful test
        await loadIntegrationStatus();
      } else {
        setPersonaplexMessage({ type: "error", text: response.data.error || "Connection failed" });
      }
    } catch (error: any) {
      setPersonaplexMessage({
        type: "error",
        text: error.response?.data?.detail || "Failed to test connection",
      });
    } finally {
      setPersonaplexTesting(false);
    }
  };

  // Twilio handlers
  const handleSaveTwilio = async () => {
    setTwilioSaving(true);
    setTwilioMessage(null);
    try {
      await api.post("/settings/twilio", {
        account_sid: twilioAccountSid,
        auth_token: twilioAuthToken,
        phone_number: twilioPhoneNumber,
        agent_id: twilioAgentId || null,
      });
      setTwilioMessage({ type: "success", text: "Twilio credentials saved successfully" });
      // Clear sensitive fields after save
      setTwilioAccountSid("");
      setTwilioAuthToken("");
      loadIntegrationStatus();
    } catch (error: any) {
      setTwilioMessage({
        type: "error",
        text: error.response?.data?.detail || "Failed to save Twilio credentials",
      });
    } finally {
      setTwilioSaving(false);
    }
  };

  const handleTestTwilio = async () => {
    setTwilioTesting(true);
    setTwilioMessage(null);
    try {
      const response = await api.post("/settings/twilio/test");
      if (response.data.success) {
        const webhook = response.data.webhook_configured
          ? `Inbound calls to ${twilioPhoneNumber || "your number"} now route to this backend.`
          : `Credentials OK, but the number's webhook was not configured: ${response.data.webhook_error || "unknown error"}`;
        setTwilioMessage({
          type: response.data.webhook_configured ? "success" : "error",
          text: `Connected to account "${response.data.account_name}". ${webhook}`,
        });
        loadIntegrationStatus();
      } else {
        setTwilioMessage({ type: "error", text: response.data.error || "Connection failed" });
      }
    } catch (error: any) {
      setTwilioMessage({
        type: "error",
        text: error.response?.data?.detail || "Failed to test connection",
      });
    } finally {
      setTwilioTesting(false);
    }
  };

  // Anthropic handlers
  const handleSaveAnthropic = async () => {
    setAnthropicSaving(true);
    setAnthropicMessage(null);
    try {
      await api.post("/settings/anthropic", { api_key: anthropicApiKey });
      setAnthropicMessage({ type: "success", text: "Anthropic API key saved successfully" });
      // Clear key after save
      setAnthropicApiKey("");
      loadIntegrationStatus();
    } catch (error: any) {
      setAnthropicMessage({
        type: "error",
        text: error.response?.data?.detail || "Failed to save API key",
      });
    } finally {
      setAnthropicSaving(false);
    }
  };

  const handleTestAnthropic = async () => {
    setAnthropicTesting(true);
    setAnthropicMessage(null);
    try {
      const response = await api.post("/settings/anthropic/test");
      if (response.data.success) {
        setAnthropicMessage({
          type: "success",
          text: `Connected! Model: ${response.data.model}`,
        });
        // Refresh status to show connected
        await loadIntegrationStatus();
      } else {
        setAnthropicMessage({ type: "error", text: response.data.error || "Connection failed" });
      }
    } catch (error: any) {
      setAnthropicMessage({
        type: "error",
        text: error.response?.data?.detail || "Failed to test connection",
      });
    } finally {
      setAnthropicTesting(false);
    }
  };

  const handleClearAnthropic = async () => {
    if (!confirm("Are you sure you want to delete your stored Anthropic API key?")) {
      return;
    }
    setAnthropicMessage(null);
    try {
      await api.delete("/settings/anthropic");
      setAnthropicMessage({ type: "success", text: "Anthropic API key deleted" });
      setAnthropicApiKey("");
      loadIntegrationStatus();
    } catch (error: any) {
      setAnthropicMessage({
        type: "error",
        text: error.response?.data?.detail || "Failed to delete API key",
      });
    }
  };

  const StatusBadge = ({ connected }: { connected: boolean }) => (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${
        connected
          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
          : "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
      }`}
    >
      {connected ? (
        <>
          <CheckCircle className="h-3 w-3" /> Connected
        </>
      ) : (
        <>
          <AlertCircle className="h-3 w-3" /> Not configured
        </>
      )}
    </span>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground mt-1">
          Manage your account settings, integrations, and preferences
        </p>
      </div>

      <Tabs defaultValue="integrations" className="space-y-6">
        <TabsList>
          <TabsTrigger value="profile" className="gap-2">
            <User className="h-4 w-4" />
            Profile
          </TabsTrigger>
          <TabsTrigger value="integrations" className="gap-2">
            <Plug className="h-4 w-4" />
            Integrations
          </TabsTrigger>
          <TabsTrigger value="notifications" className="gap-2">
            <Bell className="h-4 w-4" />
            Notifications
          </TabsTrigger>
        </TabsList>

        {/* Profile Tab */}
        <TabsContent value="profile" className="space-y-6 max-w-2xl">
          <Card>
            <CardHeader>
              <CardTitle>Profile Information</CardTitle>
              <CardDescription>
                Update your personal information and email address
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleUpdateProfile} className="space-y-4">
                {success && (
                  <div className="rounded-md bg-green-50 dark:bg-green-900/20 p-3 text-sm text-green-800 dark:text-green-400 flex items-center gap-2">
                    <CheckCircle className="h-4 w-4" />
                    {success}
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="name">Full Name</Label>
                  <Input
                    id="name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <Button type="submit" disabled={isLoading}>
                  {isLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    "Save Changes"
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Subscription</CardTitle>
              <CardDescription>
                View and manage your subscription plan
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Current Plan</span>
                  <span className="font-medium capitalize">
                    {user?.subscription?.plan || "Free"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Status</span>
                  <span className="font-medium capitalize">
                    {user?.subscription?.status || "Active"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Minutes Used</span>
                  <span className="font-medium">
                    {user?.subscription?.minutes_used || 0} /{" "}
                    {user?.subscription?.minutes_included || 0}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Integrations Tab */}
        <TabsContent value="integrations" className="space-y-6">
          {loadingStatus ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="grid gap-6 lg:grid-cols-2">
              {/* PersonaPlex Card */}
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-purple-100 dark:bg-purple-900/30">
                        <Mic className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                      </div>
                      <div>
                        <CardTitle className="text-lg">PersonaPlex</CardTitle>
                        <CardDescription>NVIDIA Voice Engine</CardDescription>
                      </div>
                    </div>
                    <StatusBadge connected={integrationStatus?.personaplex?.connected || false} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Connect to your PersonaPlex instance for full-duplex voice AI with sub-200ms latency.
                  </p>

                  <div className="space-y-2">
                    <Label htmlFor="personaplex-url">WebSocket URL</Label>
                    <Input
                      id="personaplex-url"
                      placeholder="wss://your-endpoint.runpod.net/ws"
                      value={personaplexUrl}
                      onChange={(e) => setPersonaplexUrl(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Your PersonaPlex server WebSocket endpoint (RunPod, Vast.ai, etc.)
                    </p>
                  </div>

                  {personaplexMessage && (
                    <div
                      className={`rounded-md p-3 text-sm flex items-center gap-2 ${
                        personaplexMessage.type === "success"
                          ? "bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-400"
                          : "bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400"
                      }`}
                    >
                      {personaplexMessage.type === "success" ? (
                        <CheckCircle className="h-4 w-4" />
                      ) : (
                        <XCircle className="h-4 w-4" />
                      )}
                      {personaplexMessage.text}
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      onClick={handleTestPersonaplex}
                      disabled={!personaplexUrl || personaplexTesting}
                    >
                      {personaplexTesting ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Testing...
                        </>
                      ) : (
                        "Test Connection"
                      )}
                    </Button>
                    <Button
                      onClick={handleSavePersonaplex}
                      disabled={!personaplexUrl || personaplexSaving}
                    >
                      {personaplexSaving ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        "Save"
                      )}
                    </Button>
                  </div>

                  <a
                    href="https://github.com/NVIDIA/personaplex"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                  >
                    Learn about PersonaPlex deployment
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </CardContent>
              </Card>

              {/* Twilio Card */}
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-red-100 dark:bg-red-900/30">
                        <Phone className="h-5 w-5 text-red-600 dark:text-red-400" />
                      </div>
                      <div>
                        <CardTitle className="text-lg">Twilio</CardTitle>
                        <CardDescription>Telephony Infrastructure</CardDescription>
                      </div>
                    </div>
                    <StatusBadge connected={integrationStatus?.twilio?.connected || false} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Connect your Twilio account for phone number provisioning and call handling.
                  </p>

                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="twilio-sid">Account SID</Label>
                      <Input
                        id="twilio-sid"
                        placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                        value={twilioAccountSid}
                        onChange={(e) => setTwilioAccountSid(e.target.value)}
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="twilio-token">Auth Token</Label>
                      <div className="relative">
                        <Input
                          id="twilio-token"
                          type={showTwilioToken ? "text" : "password"}
                          placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                          value={twilioAuthToken}
                          onChange={(e) => setTwilioAuthToken(e.target.value)}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                          onClick={() => setShowTwilioToken(!showTwilioToken)}
                        >
                          {showTwilioToken ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </Button>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="twilio-phone">Phone Number</Label>
                      <Input
                        id="twilio-phone"
                        placeholder="+1234567890"
                        value={twilioPhoneNumber}
                        onChange={(e) => setTwilioPhoneNumber(e.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">
                        A number you already own in this Twilio account (E.164 format). &quot;Test Connection&quot;
                        points its voice webhook at this backend.
                      </p>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="twilio-agent">Agent that answers this number</Label>
                      <select
                        id="twilio-agent"
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        value={twilioAgentId}
                        onChange={(e) => setTwilioAgentId(e.target.value)}
                      >
                        <option value="">Automatic (your single active agent)</option>
                        {agents.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name} {a.status !== "active" ? `(${a.status})` : ""}
                          </option>
                        ))}
                      </select>
                      <p className="text-xs text-muted-foreground">
                        Required if you have more than one active agent. The agent must be active to answer calls.
                      </p>
                    </div>
                  </div>

                  {twilioMessage && (
                    <div
                      className={`rounded-md p-3 text-sm flex items-center gap-2 ${
                        twilioMessage.type === "success"
                          ? "bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-400"
                          : "bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400"
                      }`}
                    >
                      {twilioMessage.type === "success" ? (
                        <CheckCircle className="h-4 w-4" />
                      ) : (
                        <XCircle className="h-4 w-4" />
                      )}
                      {twilioMessage.text}
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      onClick={handleTestTwilio}
                      disabled={twilioTesting}
                    >
                      {twilioTesting ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Testing...
                        </>
                      ) : (
                        "Test Connection"
                      )}
                    </Button>
                    <Button
                      onClick={handleSaveTwilio}
                      disabled={!twilioAccountSid || !twilioAuthToken || twilioSaving}
                    >
                      {twilioSaving ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        "Save"
                      )}
                    </Button>
                  </div>

                  <a
                    href="https://console.twilio.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                  >
                    Get credentials from Twilio Console
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </CardContent>
              </Card>

              {/* Anthropic Card */}
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-orange-100 dark:bg-orange-900/30">
                        <Brain className="h-5 w-5 text-orange-600 dark:text-orange-400" />
                      </div>
                      <div>
                        <CardTitle className="text-lg">Anthropic</CardTitle>
                        <CardDescription>Claude AI Engine</CardDescription>
                      </div>
                    </div>
                    <StatusBadge connected={integrationStatus?.anthropic?.connected || false} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Connect your Anthropic API key for intelligent reasoning and tool execution.
                  </p>

                  <div className="space-y-2">
                    <Label htmlFor="anthropic-key">API Key</Label>
                    <div className="relative">
                      <Input
                        id="anthropic-key"
                        type={showAnthropicKey ? "text" : "password"}
                        placeholder="sk-ant-api03-xxxxxxxxxxxxxxxx"
                        value={anthropicApiKey}
                        onChange={(e) => setAnthropicApiKey(e.target.value)}
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                        onClick={() => setShowAnthropicKey(!showAnthropicKey)}
                      >
                        {showAnthropicKey ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Your API key will be encrypted and stored securely
                    </p>
                  </div>

                  {anthropicMessage && (
                    <div
                      className={`rounded-md p-3 text-sm flex items-center gap-2 ${
                        anthropicMessage.type === "success"
                          ? "bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-400"
                          : "bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-400"
                      }`}
                    >
                      {anthropicMessage.type === "success" ? (
                        <CheckCircle className="h-4 w-4" />
                      ) : (
                        <XCircle className="h-4 w-4" />
                      )}
                      {anthropicMessage.text}
                    </div>
                  )}

                  <div className="flex gap-2 flex-wrap">
                    <Button
                      variant="outline"
                      onClick={handleTestAnthropic}
                      disabled={anthropicTesting}
                    >
                      {anthropicTesting ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Testing...
                        </>
                      ) : (
                        "Test Connection"
                      )}
                    </Button>
                    <Button
                      onClick={handleSaveAnthropic}
                      disabled={!anthropicApiKey || anthropicSaving}
                    >
                      {anthropicSaving ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        "Save"
                      )}
                    </Button>
                    {(integrationStatus?.anthropic?.connected || integrationStatus?.anthropic?.has_key) && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={handleClearAnthropic}
                      >
                        Clear Stored Key
                      </Button>
                    )}
                  </div>

                  <a
                    href="https://console.anthropic.com/settings/keys"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                  >
                    Get API key from Anthropic Console
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </CardContent>
              </Card>

              {/* Integration Status Summary */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Integration Status</CardTitle>
                  <CardDescription>Overview of your connected services</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between py-2 border-b">
                      <div className="flex items-center gap-2">
                        <Mic className="h-4 w-4 text-purple-500" />
                        <span>PersonaPlex</span>
                      </div>
                      {integrationStatus?.personaplex?.connected ? (
                        <span className="text-sm text-green-600 dark:text-green-400">
                          {integrationStatus.personaplex.url?.replace(/^wss?:\/\//, "").split("/")[0]}
                        </span>
                      ) : (
                        <span className="text-sm text-muted-foreground">Not configured</span>
                      )}
                    </div>
                    <div className="flex items-center justify-between py-2 border-b">
                      <div className="flex items-center gap-2">
                        <Phone className="h-4 w-4 text-red-500" />
                        <span>Twilio</span>
                      </div>
                      {integrationStatus?.twilio?.connected ? (
                        <span className="text-sm text-green-600 dark:text-green-400">
                          {integrationStatus.twilio.phone_number}
                        </span>
                      ) : (
                        <span className="text-sm text-muted-foreground">Not configured</span>
                      )}
                    </div>
                    <div className="flex items-center justify-between py-2">
                      <div className="flex items-center gap-2">
                        <Brain className="h-4 w-4 text-orange-500" />
                        <span>Anthropic</span>
                      </div>
                      {integrationStatus?.anthropic?.connected ? (
                        <span className="text-sm text-green-600 dark:text-green-400">
                          Connected
                        </span>
                      ) : (
                        <span className="text-sm text-muted-foreground">Not configured</span>
                      )}
                    </div>
                  </div>

                  {(!integrationStatus?.personaplex?.connected ||
                    !integrationStatus?.twilio?.connected ||
                    !integrationStatus?.anthropic?.connected) && (
                    <div className="mt-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-md">
                      <p className="text-sm text-yellow-800 dark:text-yellow-400 flex items-center gap-2">
                        <AlertCircle className="h-4 w-4" />
                        Configure all integrations to enable voice agents
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        {/* Notifications Tab */}
        <TabsContent value="notifications" className="max-w-2xl">
          <Card>
            <CardHeader>
              <CardTitle>Notification Preferences</CardTitle>
              <CardDescription>
                Configure how you receive notifications
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Notification settings coming soon
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
