"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Plus, Bot, Play, Pause, Edit, Trash2, AlertCircle, X } from "lucide-react";
import api from "@/lib/api";
import { Agent } from "@/types";

export default function AgentsPage() {
  const router = useRouter();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents();
  }, []);

  const fetchAgents = async () => {
    try {
      const response = await api.get("/agents");
      const data = Array.isArray(response.data) ? response.data : response.data.items || [];
      setAgents(data);
      setError(null);
    } catch (err: any) {
      const message = err.response?.data?.detail?.detail || err.response?.data?.detail || "Failed to fetch agents";
      setError(message);
      console.error("Failed to fetch agents:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleStatus = async (agentId: string, currentStatus: string) => {
    setError(null);
    setSuccessMessage(null);
    try {
      const newStatus = currentStatus === "active" ? "paused" : "active";
      const endpoint = newStatus === "active" ? "activate" : "pause";
      await api.post(`/agents/${agentId}/${endpoint}`);
      setSuccessMessage(`Agent ${newStatus === "active" ? "activated" : "paused"} successfully`);
      fetchAgents();
      // Auto-clear success message after 3 seconds
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      const message = err.response?.data?.detail?.detail || err.response?.data?.detail || "Failed to update agent status";
      setError(message);
      console.error("Failed to toggle agent status:", err);
    }
  };

  const handleDelete = async (agentId: string) => {
    if (!confirm("Are you sure you want to delete this agent?")) return;

    setError(null);
    setSuccessMessage(null);
    try {
      await api.delete(`/agents/${agentId}`);
      setSuccessMessage("Agent deleted successfully");
      fetchAgents();
      // Auto-clear success message after 3 seconds
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      const message = err.response?.data?.detail?.detail || err.response?.data?.detail || "Failed to delete agent";
      setError(message);
      console.error("Failed to delete agent:", err);
    }
  };

  const getAgentTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      receptionist: "bg-blue-100 text-blue-800",
      scheduler: "bg-green-100 text-green-800",
      reminder: "bg-orange-100 text-orange-800",
      qualifier: "bg-purple-100 text-purple-800",
    };
    return colors[type] || "bg-gray-100 text-gray-800";
  };

  const getStatusBadge = (status: string) => {
    if (status === "active") {
      return <Badge className="bg-green-500">Active</Badge>;
    }
    if (status === "paused") {
      return <Badge variant="secondary">Paused</Badge>;
    }
    return <Badge variant="outline">Draft</Badge>;
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading agents...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Error Banner */}
      {error && (
        <Alert variant="destructive" className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setError(null)}>
            <X className="h-4 w-4" />
          </Button>
        </Alert>
      )}

      {/* Success Banner */}
      {successMessage && (
        <Alert className="bg-green-50 text-green-800 border-green-200 flex items-center justify-between">
          <AlertDescription>{successMessage}</AlertDescription>
          <Button variant="ghost" size="sm" onClick={() => setSuccessMessage(null)}>
            <X className="h-4 w-4" />
          </Button>
        </Alert>
      )}

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">AI Agents</h1>
          <p className="text-muted-foreground mt-1">
            Manage your voice agents and their configurations
          </p>
        </div>
        <Button onClick={() => router.push("/dashboard/agents/new")}>
          <Plus className="mr-2 h-4 w-4" />
          Create Agent
        </Button>
      </div>

      {agents.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No agents yet</CardTitle>
            <CardDescription>
              Create your first AI voice agent to get started
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => router.push("/dashboard/agents/new")}>
              <Plus className="mr-2 h-4 w-4" />
              Create Your First Agent
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <Card key={agent.id} className="hover:shadow-lg transition-shadow">
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
                      <Bot className="h-6 w-6 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-lg">{agent.name}</CardTitle>
                      <div className="flex gap-2 mt-1">
                        <Badge className={getAgentTypeColor(agent.type)}>
                          {agent.type}
                        </Badge>
                        {getStatusBadge(agent.status)}
                      </div>
                    </div>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <p className="text-muted-foreground">Total Calls</p>
                      <p className="font-semibold">{agent.analytics.total_calls}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Total Minutes</p>
                      <p className="font-semibold">{agent.analytics.total_minutes}</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleToggleStatus(agent.id, agent.status)}
                      className="flex-1"
                    >
                      {agent.status === "active" ? (
                        <>
                          <Pause className="mr-1 h-3 w-3" />
                          Pause
                        </>
                      ) : (
                        <>
                          <Play className="mr-1 h-3 w-3" />
                          Activate
                        </>
                      )}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => router.push(`/dashboard/agents/${agent.id}`)}
                    >
                      <Edit className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDelete(agent.id)}
                    >
                      <Trash2 className="h-3 w-3 text-destructive" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
