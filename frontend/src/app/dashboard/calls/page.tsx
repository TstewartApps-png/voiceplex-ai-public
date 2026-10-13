"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Phone, Clock, TrendingUp, TrendingDown, Minus, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { Call } from "@/types";
import { formatDateTime, formatDuration, formatPhoneNumber } from "@/lib/utils";

export default function CallsPage() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [stats, setStats] = useState({
    total: 0,
    completed: 0,
    avgDuration: 0,
  });

  useEffect(() => {
    fetchCalls();
  }, []);

  const fetchCalls = async () => {
    try {
      const response = await api.get("/calls", { params: { limit: 50 } });
      const callsData = response.data.items || [];
      setCalls(callsData);

      const completed = callsData.filter((c: Call) => c.status === "completed");
      const totalDuration = completed.reduce((sum: number, c: Call) => sum + (c.duration_seconds || 0), 0);

      setStats({
        total: callsData.length,
        completed: completed.length,
        avgDuration: completed.length > 0 ? Math.round(totalDuration / completed.length) : 0,
      });
    } catch (error) {
      console.error("Failed to fetch calls:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; text: string }> = {
      completed: { variant: "default", text: "Completed" },
      in_progress: { variant: "secondary", text: "In Progress" },
      failed: { variant: "destructive", text: "Failed" },
      no_answer: { variant: "outline", text: "No Answer" },
    };
    const config = variants[status] || { variant: "outline" as const, text: status };
    return <Badge variant={config.variant}>{config.text}</Badge>;
  };

  const getOutcomeBadge = (outcome?: string) => {
    if (!outcome) return null;
    const colors: Record<string, string> = {
      appointment_scheduled: "bg-green-100 text-green-800",
      message_taken: "bg-blue-100 text-blue-800",
      transferred: "bg-purple-100 text-purple-800",
      information_provided: "bg-yellow-100 text-yellow-800",
    };
    return (
      <Badge className={colors[outcome] || "bg-gray-100 text-gray-800"}>
        {outcome.replace(/_/g, " ")}
      </Badge>
    );
  };

  const getSentimentIcon = (score?: number) => {
    if (!score) return <Minus className="h-4 w-4 text-gray-400" />;
    if (score > 0.3) return <TrendingUp className="h-4 w-4 text-green-600" />;
    if (score < -0.3) return <TrendingDown className="h-4 w-4 text-red-600" />;
    return <Minus className="h-4 w-4 text-yellow-600" />;
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading calls...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Call Logs</h1>
        <p className="text-muted-foreground mt-1">
          View and analyze your voice agent conversations
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Calls</CardTitle>
            <Phone className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.total}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Completed</CardTitle>
            <Phone className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.completed}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Duration</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatDuration(stats.avgDuration)}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent Calls</CardTitle>
        </CardHeader>
        <CardContent>
          {calls.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              No calls yet. Your call history will appear here.
            </p>
          ) : (
            <div className="space-y-3">
              {calls.map((call) => (
                <div
                  key={call.id}
                  className="flex items-center justify-between p-4 border rounded-lg hover:bg-accent transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-4 flex-1">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                      <Phone className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <p className="font-medium">
                          {call.caller?.name || "Unknown Caller"}
                        </p>
                        {getStatusBadge(call.status)}
                        {getOutcomeBadge(call.outcome)}
                      </div>
                      <div className="flex items-center gap-3 text-sm text-muted-foreground">
                        <span>{formatPhoneNumber(call.from_number)}</span>
                        <span>-</span>
                        <span>{formatDateTime(call.initiated_at)}</span>
                        {call.duration_seconds && (
                          <>
                            <span>-</span>
                            <span>{formatDuration(call.duration_seconds)}</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {getSentimentIcon(call.sentiment_analysis?.overall_score)}
                      <Button variant="ghost" size="sm">
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
